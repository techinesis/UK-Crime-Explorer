"""AI chat: tool registry, Police system prompt, and the tool-use loop.

This is the framework-agnostic half of the chat feature (no FastAPI here, by the
same convention as the rest of ``core/``). It exposes:

* :data:`TOOLS` — the Anthropic tool definitions for Phase 1
  (``set_filters``, ``query_data``, ``get_weights``, ``read_docs``).
* :func:`dispatch_tool` — execute one tool call, returning the LLM-facing result,
  an optional dashboard *action*, and a short human-readable summary.
* :func:`run_chat` — the agentic loop. The Anthropic client is **injected** so
  the API layer owns key/availability handling and tests can pass a fake.
* :data:`POLICE_SYSTEM_PROMPT` — the Phase 1 (Police / policy planner) persona.

Heavy/optional dependencies (``anthropic``, ``rank_bm25``, ``python-dotenv``) are
imported lazily/defensively so that importing this module never breaks the rest
of the backend — important because the lean Vercel function imports
``api.main`` (hence this module) but does not ship ``rank_bm25``/``slowapi``.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterator

from core.composite import (
    METRIC_COLUMNS,
    VALID_METRICS,
    VALID_SEVERITY_BASES,
    compute_map_values,
)
from core.data import (
    BOROUGH_ALL,
    CANONICAL_CATEGORY,
    DEFAULT_CITY,
    ID_COLUMN_BY_LEVEL,
    KNOWN_CITIES,
    TIER_ALL,
    TIERS,
    aggregate,
    filter_crime_df,
    get_crime_long,
)
from core.geometry import LEVELS
from core.weights import weights_records

# backend/core/chat.py -> parents[0]=core, [1]=backend, [2]=repo root
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = Path(__file__).resolve().parents[2]

# Load backend/.env for local dev so `uvicorn api.main:app` sees ANTHROPIC_API_KEY
# without an explicit --env-file. python-dotenv ships with uvicorn[standard]
# locally; it is absent from the lean Vercel function, where env vars come from
# the project settings instead — hence the defensive guard.
try:  # pragma: no cover - trivial best-effort env load
    from dotenv import load_dotenv

    load_dotenv(_BACKEND_DIR / ".env")
except Exception:  # noqa: BLE001 - never let env loading break import
    pass

# Default model for the chat. Sonnet gives the best tool-use cost/latency balance
# for this workload; override with ANTHROPIC_MODEL for experiments.
DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# Cap conversation context to the most recent N turns (spec risk mitigation:
# bound LLM cost / context growth).
MAX_CONTEXT_MESSAGES = 10

# Hard cap on tool-use round-trips per request, so a misbehaving model cannot
# loop forever.
MAX_TOOL_ITERATIONS = 6

# Filter dimensions defaulted when query_data omits them. Mirrors the dashboard's
# "no filter" sentinels (see core.data) so a bare query == the unfiltered view.
# `city` is overridden per-request with the city the user is currently viewing
# (threaded through dispatch_tool from current_filters).
DEFAULT_FILTERS: dict[str, Any] = {
    "categories": [],
    "tier": TIER_ALL,
    "year": None,
    "months": [],
    "borough": BOROUGH_ALL,
    "level": "lsoa",
    "metric": "raw",
    "severity_basis": "mean",
    "city": DEFAULT_CITY,
}

# The canonical 14 crime-category labels (the values of the slug/typo->name map).
# Tool schemas enum these and normalize_filters resolves case-insensitively, so a
# model-invented label ("Drug Offences") can't silently filter the map to nothing.
VALID_CATEGORIES: list[str] = sorted(set(CANONICAL_CATEGORY.values()))
_CATEGORY_LOOKUP: dict[str, str] = {
    **{slug.lower(): name for slug, name in CANONICAL_CATEGORY.items()},
    **{name.lower(): name for name in VALID_CATEGORIES},
}

# Tier values are matched by exact string equality in filter_crime_df, so the
# same silent-empty-result hazard as categories applies; resolve case-insensitively.
_TIER_LOOKUP: dict[str, str] = {t.lower(): t for t in TIERS}

# What query_data can rank: geographic units at `level` (the default), or the
# crime-category / time dimensions ("top 3 crime types", trends, seasonality).
GROUP_BY_DIMENSIONS: tuple[str, ...] = ("unit", "category", "year", "month")


# --------------------------------------------------------------------------- #
# System prompt: one shared core + a per-persona preamble
# --------------------------------------------------------------------------- #
#
# The data layer is identical across all three personas (Phase 2 spec); only the
# audience, tone, depth, and example emphasis change. We therefore keep the
# dashboard facts + tool rules + hard rules in ONE shared block and swap only a
# short persona preamble. _system_blocks() emits the shared core FIRST (with the
# prompt-cache marker) so the cached prefix is identical regardless of persona —
# switching persona still hits the cache.

_SHARED_CORE = """\
You are the assistant inside the **London Crime Explorer**, a dashboard that maps
recorded crime and exposes a composite *police-demand signal* —
`crime count × severity × preventability` — at LSOA, ward, and borough level.
London is the default city; the dashboard's City selector also offers Birmingham,
Manchester, and Liverpool. Your tools accept a `city` field that defaults to the
city the user is currently viewing — only set it when the user explicitly asks
about a different city.

## What the dashboard means
- **Severity** comes from the Cambridge Crime Harm Index (CCHI) 2020 — recommended
  sentence in days — available on a *mean* or *median* basis (the `severity_basis`).
- **Preventability** is a 0.1–1.0 multiplier per crime category, anchored in
  hot-spot policing literature, each with a confidence rating and a one-line citation.
- **Composite** = crime count × severity × preventability. The five map metrics are
  `raw`, `share`, `severity`, `preventability`, `composite`.

## How to act — you have tools, use them
You operate in three implicit modes; pick based on the user's intent:

1. **Navigate** — when the user wants to *see* or *filter* something on the map
   ("show me…", "filter to…", "map robbery in Westminster"), call **set_filters**.
   This updates the dashboard the user is looking at.
2. **Query** — when the user asks a data question ("which/highest/compare/how many"),
   call **query_data** to get ranked, grounded numbers. This does NOT change their view.
   `group_by` picks the dimension: places (`unit`, the default), crime types
   (`category` — use this for "top crime types"), or trends over time (`year`/`month`).
   Recorded data covers 2008–2016 and 2023 onwards; there is no 2017–2022 data, and
   a few recent months are missing — empty results carry a hint saying what exists.
   Category detail exists only from 2023 onwards (2008–2016 are total counts only),
   so filter category questions to 2023+ years.
3. **Explain** — for methodology / "why" / "how is X calculated" questions, call
   **read_docs** (and **get_weights** for the preventability/severity table). Cite the
   literature anchors (e.g. Weisburd 2015, Braga 2019) by name in your answer.

You may call several tools before answering. After tools return, write the answer
in natural language.

## Hard rules (do not break these)
- **Every quantitative claim — counts, rankings, multipliers, comparisons — MUST come
  from a tool result.** Never invent or estimate a number. If you have not called a
  tool for a figure, do not state it.
- If a tool returns an error, tell the user plainly that the data could not be
  retrieved; do not improvise a number to cover the gap.
- **You never decide or prescribe an allocation of officers, patrols, or resources.**
  You rank and explain; the deployment decision always stays with the human planner.
  For "where should we deploy / how many officers / what should we do" questions,
  answer with the composite (or preventability) ranking via `query_data`, then state
  explicitly that the deployment decision remains with the planner. Never give an
  officer count and never say "deploy N here".
- **You cannot forecast future crime or compute an allocation — those tools are not
  connected to you yet.** If asked for a forecast figure or an optimal allocation, say
  so plainly (the dashboard's forecast view is a prototype, not a model you can read)
  and offer the current ranking instead. Never fabricate a forward-looking or
  allocation number.
- Do not claim the dashboard view changed unless you actually called set_filters.
- Write replies in plain GitHub-flavoured markdown (bold, lists, tables). Never use
  LaTeX or math delimiters like $$…$$ — the chat renders them as literal text.

Stay grounded, stay useful, and keep the human in the loop."""


# Per-persona preamble. Same tools, same data — only audience, tone, and emphasis
# change (Phase 2 spec persona table). Order in _system_blocks: shared core, then
# this preamble, then the live "current view".
PERSONAS: dict[str, dict[str, str]] = {
    "police": {
        "name": "Police",
        "preamble": (
            "You are speaking to a **police / policy planner**: a non-data-scientist "
            "who needs clear, operational, plain-language answers. Be concise and "
            "professional. Lead with what matters operationally (where demand is highest, "
            "how this month compares), and prefer short paragraphs and tight bullet lists."
        ),
    },
    "examiner": {
        "name": "Examiner",
        "preamble": (
            "You are speaking to an **academic examiner**: rigorous and methodology-aware. "
            "Be precise about *why* each modelling choice was made, name the literature and "
            "evidence behind it (CCHI 2020 for severity; Weisburd 2015, Braga 2019 for "
            "preventability), and state what would differ under an alternative scheme (e.g. "
            "median vs mean CCHI). Surface assumptions and limitations honestly. Still ground "
            "every number in a tool call."
        ),
    },
    "community": {
        "name": "Community",
        "preamble": (
            "You are speaking to a **community member**: accessible and non-technical. "
            "Avoid jargon (explain terms like 'composite' or 'LSOA' in plain words). "
            "Emphasise transparency and ethics — be clear about what the model does and does "
            "NOT do, that it describes recorded crime and ranks areas but does not decide "
            "policing, and that a human makes any deployment decision. Be reassuring and honest "
            "about limitations rather than alarming."
        ),
    },
}

DEFAULT_PERSONA = "police"


def resolve_persona(persona: str | None) -> str:
    """Map a requested persona id to a known one; unknown/missing -> police."""
    if persona and str(persona).lower() in PERSONAS:
        return str(persona).lower()
    return DEFAULT_PERSONA


# Back-compat: the composed Police prompt (preamble + shared core).
POLICE_SYSTEM_PROMPT = f"{PERSONAS['police']['preamble']}\n\n{_SHARED_CORE}"


# --------------------------------------------------------------------------- #
# Tool definitions (Anthropic tool-use schema)
# --------------------------------------------------------------------------- #

_FILTER_PROPERTIES: dict[str, Any] = {
    "categories": {
        "type": "array",
        "items": {"type": "string", "enum": VALID_CATEGORIES},
        "description": "Crime categories (exact canonical names). Empty/omitted = all categories.",
    },
    "city": {
        "type": "string",
        "enum": list(KNOWN_CITIES),
        "description": (
            "Which city's data to use. Defaults to the city the user is currently "
            "viewing — only set this when the user explicitly asks about a different city."
        ),
    },
    "tier": {
        "type": "string",
        "enum": list(TIERS),
        "description": "Preventability tier filter: 'All tiers', 'High', 'Medium', or 'Low'.",
    },
    "year": {
        "type": ["integer", "null"],
        "description": "Calendar year to filter to (e.g. 2024). Omit or null = all years.",
    },
    "months": {
        "type": "array",
        "items": {"type": "integer"},
        "description": "Month numbers 1-12 to include (e.g. [6,7,8] for summer). Empty/omitted = all months.",
    },
    "borough": {
        "type": "string",
        "description": (
            "Borough/district name within the selected city (e.g. 'Westminster'). "
            "'All boroughs' = no borough filter."
        ),
    },
    "level": {
        "type": "string",
        "enum": list(LEVELS),
        "description": "Aggregation level for the map / ranking.",
    },
    "metric": {
        "type": "string",
        "enum": list(VALID_METRICS),
        "description": "Which demand metric to display/rank by.",
    },
    "severity_basis": {
        "type": "string",
        "enum": list(VALID_SEVERITY_BASES),
        "description": "CCHI basis used by the severity and composite metrics.",
    },
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "set_filters",
        "description": (
            "Update the dashboard the user is viewing: set crime categories, city, tier, "
            "year, months, borough, aggregation level, metric, and/or severity basis. "
            "Only include the fields you want to change. Use this when the user wants "
            "to SEE or FILTER something on the map. Returns the filters that were applied."
        ),
        "input_schema": {
            "type": "object",
            "properties": _FILTER_PROPERTIES,
            "additionalProperties": False,
        },
    },
    {
        "name": "query_data",
        "description": (
            "Answer a data question without changing the user's view. Aggregates the "
            "crime data under the given filters and returns the top-ranked entries plus "
            "the value range. Same filter fields as set_filters, plus 'top_n' and "
            "'group_by' (rank places, crime categories, or time periods). To rank "
            "across all units of a level, leave the higher-level filters at their 'All …' "
            "defaults (e.g. borough='All boroughs' when ranking boroughs)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                **_FILTER_PROPERTIES,
                "top_n": {
                    "type": "integer",
                    "description": "How many top-ranked entries to return (default 5, max 50).",
                },
                "group_by": {
                    "type": "string",
                    "enum": list(GROUP_BY_DIMENSIONS),
                    "description": (
                        "What to rank: 'unit' (default) = places at the chosen level; "
                        "'category' = crime types; 'year' or 'month' = totals over time "
                        "(set top_n to cover the range, e.g. 13 years / 12 months)."
                    ),
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_weights",
        "description": (
            "Return the full category weights table: per crime category, the CCHI "
            "severity weights (mean & median), the preventability multiplier, its tier "
            "and confidence, and the one-line literature anchor. Use for methodology "
            "questions about severity or preventability."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "read_docs",
        "description": (
            "Look up project documentation to explain methodology (preventability, "
            "severity, composite, data sources, ethics). Returns the most relevant "
            "documentation chunks for the given topic."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "What to look up, e.g. 'preventability', 'severity CCHI', 'composite metric'.",
                }
            },
            "required": ["topic"],
            "additionalProperties": False,
        },
    },
]


# --------------------------------------------------------------------------- #
# Filter argument normalisation
# --------------------------------------------------------------------------- #


def normalize_filters(args: dict[str, Any]) -> dict[str, str | int | list | None]:
    """Validate + coerce LLM-supplied filter args, keeping only provided keys.

    The returned dict is a ``Partial<MapRequest>`` (snake_case): exactly the keys
    the model set, validated. This is both the ``set_filters`` action payload and
    the overlay used by ``query_data``. Raises ``ValueError`` on a bad enum value
    so the model gets a tool error it can recover from.
    """
    out: dict[str, Any] = {}

    if args.get("categories") is not None:
        resolved: list[str] = []
        unknown: list[str] = []
        for raw in args["categories"]:
            canonical = _CATEGORY_LOOKUP.get(str(raw).strip().lower())
            (resolved if canonical else unknown).append(canonical or str(raw))
        if unknown:
            raise ValueError(
                f"unknown categories {unknown}; expected exact names from {VALID_CATEGORIES}"
            )
        out["categories"] = resolved

    if args.get("city"):
        city = str(args["city"]).strip().lower()
        if city not in KNOWN_CITIES:
            raise ValueError(f"unknown city {args['city']!r}; expected one of {list(KNOWN_CITIES)}")
        out["city"] = city

    if args.get("tier"):
        tier = _TIER_LOOKUP.get(str(args["tier"]).strip().lower())
        if tier is None:
            raise ValueError(f"unknown tier {args['tier']!r}; expected one of {list(TIERS)}")
        out["tier"] = tier

    if "year" in args:
        year = args["year"]
        out["year"] = None if year in (None, "", "All years") else int(year)

    if args.get("months") is not None:
        months = [int(m) for m in args["months"]]
        bad = [m for m in months if not 1 <= m <= 12]
        if bad:
            raise ValueError(f"months must be in 1-12, got {bad}")
        out["months"] = months

    if args.get("borough"):
        borough = args["borough"]
        # Models occasionally send a one-element list; unwrap it rather than
        # str()-ing it into "['Camden']" (which silently matches no borough).
        if isinstance(borough, (list, tuple)):
            if len(borough) != 1:
                raise ValueError(f"borough accepts a single name, got {list(borough)}")
            borough = borough[0]
        out["borough"] = str(borough)

    if args.get("level"):
        level = str(args["level"]).lower()
        if level not in LEVELS:
            raise ValueError(f"unknown level {args['level']!r}; expected one of {list(LEVELS)}")
        out["level"] = level

    if args.get("metric"):
        metric = str(args["metric"]).lower()
        if metric not in VALID_METRICS:
            raise ValueError(f"unknown metric {args['metric']!r}; expected one of {list(VALID_METRICS)}")
        out["metric"] = metric

    if args.get("severity_basis"):
        basis = str(args["severity_basis"]).lower()
        if basis not in VALID_SEVERITY_BASES:
            raise ValueError(
                f"unknown severity_basis {args['severity_basis']!r}; "
                f"expected one of {list(VALID_SEVERITY_BASES)}"
            )
        out["severity_basis"] = basis

    return out


def _filters_summary(filters: dict[str, Any]) -> str:
    """Compact human-readable rendering of a (partial) filter dict for audit badges."""
    parts: list[str] = []
    for key in ("city", "categories", "tier", "year", "months", "borough", "level", "metric", "severity_basis"):
        if key not in filters:
            continue
        value = filters[key]
        if isinstance(value, list):
            value = "[" + ", ".join(str(v) for v in value) + "]"
        parts.append(f"{key}={value}")
    return ", ".join(parts) if parts else "(no changes)"


# --------------------------------------------------------------------------- #
# Tool implementations
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=4)
def _lsoa_name_lookup(city: str) -> dict[str, str]:
    """lsoa_code -> lsoa_name for one city, for labelling LSOA-level rankings."""
    df = get_crime_long(city)
    pairs = df[["lsoa_code", "lsoa_name"]].drop_duplicates()
    return {str(code): str(name) for code, name in pairs.itertuples(index=False, name=None)}


@lru_cache(maxsize=4)
def _borough_lookup(city: str) -> dict[str, str]:
    """lowercase borough -> proper-cased name, from the city's own data."""
    df = get_crime_long(city)
    return {str(b).lower(): str(b) for b in df["borough"].dropna().unique()}


def _resolve_borough(borough: str, city: str) -> str:
    """Resolve a model-supplied borough to the exact name the data uses.

    filter_crime_df matches boroughs by exact string equality, so 'camden' would
    silently match nothing — the same hazard as categories/tiers. Unknown names
    raise with the city's valid list so the model can self-correct.
    """
    if not borough or borough == BOROUGH_ALL:
        return borough
    match = _borough_lookup(city).get(borough.strip().lower())
    if match is None:
        valid = sorted(_borough_lookup(city).values())
        raise ValueError(f"unknown borough {borough!r} for {city}; expected one of {valid}")
    return match


def _unit_name(level: str, unit_id: str, city: str) -> str:
    """Best-effort display name for a unit id. Borough ids are already names;
    LSOA codes map to a name; ward codes have no friendly name available here."""
    if level == "lsoa":
        return _lsoa_name_lookup(city).get(unit_id, unit_id)
    return unit_id


def tool_set_filters(
    args: dict[str, Any], *, default_city: str = DEFAULT_CITY
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Validate the requested filter change. Returns (llm_result, action, summary).

    ``default_city`` (the city the user is viewing) scopes borough resolution
    when the model doesn't switch city in the same call.
    """
    payload = normalize_filters(args)
    if "borough" in payload:
        payload["borough"] = _resolve_borough(payload["borough"], payload.get("city", default_city))
    action = {"type": "set_filters", "payload": payload}
    result = {"applied": payload}
    return result, action, _filters_summary(payload)


def tool_query_data(
    args: dict[str, Any], *, default_city: str = DEFAULT_CITY
) -> tuple[dict[str, Any], None, str]:
    """Aggregate + rank under the given filters. Returns (llm_result, None, summary).

    Re-implements /api/map's aggregation via the public ``core`` functions (the
    private _map_payload is intentionally not imported) and adds a top-N ranking.
    ``default_city`` is the city the user is currently viewing; an explicit
    ``city`` in ``args`` overrides it. ``group_by`` picks the ranking dimension:
    geographic units at ``level`` (default), crime categories, or years/months.
    """
    overlay = normalize_filters(args)
    filters = {**DEFAULT_FILTERS, "city": default_city, **overlay}

    group_by = str(args.get("group_by") or "unit").strip().lower()
    if group_by not in GROUP_BY_DIMENSIONS:
        raise ValueError(
            f"unknown group_by {args.get('group_by')!r}; expected one of {list(GROUP_BY_DIMENSIONS)}"
        )

    # Time series are small (≤13 years / 12 months) and only useful whole: a
    # default top-5 would show the five BIGGEST years and hide the recent ones.
    default_top_n = 50 if group_by in ("year", "month") else 5
    top_n_raw = args.get("top_n", default_top_n)
    try:
        top_n = max(1, min(50, int(top_n_raw)))
    except (TypeError, ValueError):
        top_n = default_top_n

    level = filters["level"]
    metric = filters["metric"]
    severity_basis = filters["severity_basis"]
    city = filters["city"]
    filters["borough"] = _resolve_borough(filters["borough"], city)

    df = get_crime_long(city)
    filtered = filter_crime_df(
        df,
        categories=tuple(filters["categories"]),
        tier=filters["tier"],
        year=filters["year"],
        months=tuple(filters["months"]),
        borough=filters["borough"],
    )
    if group_by == "unit":
        aggregated = aggregate(filtered, level)
        id_col = ID_COLUMN_BY_LEVEL[level]
    else:
        # Rank crime types or time periods instead of places: same metric maths,
        # different grouping key. observed=True because `category` is categorical.
        aggregated = (
            filtered.groupby(group_by, as_index=False, observed=True)[list(METRIC_COLUMNS)].sum()
        )
        aggregated[group_by] = aggregated[group_by].astype(str)
        id_col = group_by

    if aggregated.empty:
        # compute_map_values on an empty frame yields NaN bounds; short-circuit.
        vmin, vmax = 0.0, 0.0
        top: list[dict[str, Any]] = []
    else:
        values, vmin, vmax = compute_map_values(aggregated, metric, severity_basis)
        ranked = aggregated.assign(_value=values.to_numpy()).sort_values("_value", ascending=False)
        top_rows = ranked.head(top_n)
        top = [
            {
                "id": str(row[id_col]),
                "name": (
                    _unit_name(level, str(row[id_col]), city)
                    if group_by == "unit"
                    else str(row[id_col])
                ),
                "value": round(float(row["_value"]), 2),
                "crime_count": int(round(float(row["crime_count"]))),
            }
            for _, row in top_rows.iterrows()
        ]

    result = {
        "metric": metric,
        "level": level,
        "group_by": group_by,
        "severity_basis": severity_basis,
        "filters_applied": {k: filters[k] for k in DEFAULT_FILTERS},
        "unit_count": int(len(aggregated)),
        "total_crime_count": int(round(float(aggregated["crime_count"].sum()))) if not aggregated.empty else 0,
        "vmin": round(float(vmin), 2),
        "vmax": round(float(vmax), 2),
        "top": top,
    }
    # The 2008-2016 rows are total counts only (one 'Other crime' bucket per
    # LSOA-month); category-level detail starts in 2023. Without this caveat a
    # whole-history category ranking reads as "80% of crime is Other crime".
    if group_by == "category" and (filters["year"] is None or int(filters["year"]) <= 2016):
        result["note"] = (
            "category detail exists only from 2023 onwards; the 2008-2016 rows are "
            "total counts stored under 'Other crime'. For category rankings or "
            "shares, filter to a year >= 2023 (or state this caveat)."
        )

    if result["total_crime_count"] == 0:
        # Tell the model WHY it's empty so it explains coverage instead of
        # inventing a backend failure (the snapshot has a 2017-2022 gap, and the
        # recent window is missing occasional months).
        hint: dict[str, Any] = {
            "note": "no recorded crime matched these filters",
            "available_years": sorted(int(y) for y in df["year"].unique()),
        }
        if filters["year"] is not None:
            year_rows = df[df["year"] == int(filters["year"])]
            if not year_rows.empty:
                hint["available_months_in_year"] = sorted(
                    int(m) for m in year_rows["month"].unique()
                )
        if filters["categories"]:
            hint["category_coverage"] = (
                "category-level data exists only from 2023 onwards; "
                "2008-2016 rows are total counts without categories"
            )
        result["hint"] = hint
    dimension = level if group_by == "unit" else group_by
    label = ", ".join(f"{t['name']} ({t['value']:g})" for t in top[:3])
    summary = (
        f"{dimension}/{metric}: top {len(top)} — {label}"
        if top
        else f"{dimension}/{metric}: no rows matched"
    )
    return result, None, summary


def tool_get_weights(args: dict[str, Any]) -> tuple[dict[str, Any], None, str]:
    """Return the category weights table with literature anchors."""
    rows = weights_records()
    result = {"categories": rows}
    return result, None, f"{len(rows)} categories with severity + preventability anchors"


def tool_read_docs(args: dict[str, Any]) -> tuple[dict[str, Any], None, str]:
    """RAG lookup over the project docs corpus (BM25)."""
    topic = str(args.get("topic") or args.get("query") or "").strip()
    try:
        hits = DOC_INDEX.search(topic, k=3)
    except ImportError:
        # rank_bm25 not installed (e.g. lean prod function) — degrade gracefully.
        return (
            {"topic": topic, "chunks": [], "note": "Documentation search is unavailable."},
            None,
            "docs unavailable (rank_bm25 missing)",
        )

    chunks = [{"source": h.source, "text": h.text} for h in hits]
    sources = sorted({h.source for h in hits})
    summary = f"{len(chunks)} doc chunk(s): {', '.join(sources)}" if chunks else "no matching docs"
    return {"topic": topic, "chunks": chunks}, None, summary


_TOOL_DISPATCH: dict[str, Callable[..., tuple[dict[str, Any], dict[str, Any] | None, str]]] = {
    "set_filters": tool_set_filters,
    "query_data": tool_query_data,
    "get_weights": tool_get_weights,
    "read_docs": tool_read_docs,
}


def dispatch_tool(
    name: str, args: dict[str, Any], *, default_city: str = DEFAULT_CITY
) -> tuple[dict[str, Any], dict[str, Any] | None, str]:
    """Execute one tool call.

    Returns ``(llm_result, action_or_None, summary)``. Tool errors are caught and
    returned as an error result (with no action) so the model can recover and tell
    the user, rather than crashing the request. ``default_city`` (the city the user
    is viewing) scopes the filter tools; get_weights/read_docs are city-agnostic.
    """
    fn = _TOOL_DISPATCH.get(name)
    if fn is None:
        return {"error": f"unknown tool {name!r}"}, None, f"unknown tool {name!r}"
    kwargs: dict[str, Any] = (
        {"default_city": default_city} if name in ("set_filters", "query_data") else {}
    )
    try:
        return fn(args or {}, **kwargs)
    except Exception as exc:  # noqa: BLE001 - surface tool errors to the model
        return {"error": str(exc)}, None, f"error: {exc}"


# --------------------------------------------------------------------------- #
# RAG corpus (BM25 over the repo's own docs)
# --------------------------------------------------------------------------- #

_README_PATH = _REPO_ROOT / "README.md"
_MAIN_PY_PATH = _BACKEND_DIR / "api" / "main.py"
_PREPARE_WEIGHTS_PATH = _BACKEND_DIR / "scripts" / "prepare_category_weights.py"

_MIN_CHUNK_CHARS = 40
_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class DocChunk:
    source: str
    text: str


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _readme_chunks(path: Path) -> list[DocChunk]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    sections = text.split("\n## ")
    chunks: list[DocChunk] = []
    for i, section in enumerate(sections):
        body = section if i == 0 else "## " + section
        body = body.strip()
        if len(body) >= _MIN_CHUNK_CHARS:
            chunks.append(DocChunk(source="README.md", text=body))
    return chunks


def _py_docstring_chunks(path: Path, source_label: str) -> list[DocChunk]:
    """Module docstring + each top-level function docstring (e.g. FastAPI routes)."""
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
    except (OSError, SyntaxError):
        return []

    chunks: list[DocChunk] = []
    module_doc = ast.get_docstring(tree)
    if module_doc and len(module_doc) >= _MIN_CHUNK_CHARS:
        chunks.append(DocChunk(source=source_label, text=module_doc.strip()))

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node)
            if doc and len(doc) >= _MIN_CHUNK_CHARS:
                chunks.append(DocChunk(source=source_label, text=f"{node.name}: {doc.strip()}"))
    return chunks


def _prepare_weights_chunks(path: Path) -> list[DocChunk]:
    """Module docstring + the PREVENTABILITY_14 / CCHI_GROUPS_14 literal blocks.

    The literature anchors (Weisburd, Braga, …) live inside PREVENTABILITY_14, so
    indexing that block lets methodology questions cite them.
    """
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
    except (OSError, SyntaxError):
        return []

    label = "prepare_category_weights.py"
    chunks: list[DocChunk] = []
    module_doc = ast.get_docstring(tree)
    if module_doc and len(module_doc) >= _MIN_CHUNK_CHARS:
        chunks.append(DocChunk(source=label, text=module_doc.strip()))

    wanted = {"PREVENTABILITY_14", "CCHI_GROUPS_14"}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = {t.id for t in node.targets if isinstance(t, ast.Name)}
        hit = names & wanted
        if not hit:
            continue
        segment = ast.get_source_segment(text, node)
        if segment:
            chunks.append(DocChunk(source=label, text=segment.strip()))
    return chunks


def _load_corpus() -> list[DocChunk]:
    return [
        *_readme_chunks(_README_PATH),
        *_py_docstring_chunks(_MAIN_PY_PATH, "api/main.py"),
        *_prepare_weights_chunks(_PREPARE_WEIGHTS_PATH),
    ]


class _DocIndex:
    """Lazy in-memory BM25 index over the repo docs. Built once on first search."""

    def __init__(self) -> None:
        self._bm25: Any = None
        self._chunks: list[DocChunk] = []
        self._built = False

    def _ensure_built(self) -> None:
        if self._built:
            return
        from rank_bm25 import BM25Okapi  # raises ImportError if absent (handled by caller)

        self._chunks = _load_corpus()
        tokenized = [_tokenize(c.text) for c in self._chunks]
        self._bm25 = BM25Okapi(tokenized) if tokenized else None
        self._built = True

    def search(self, query: str, k: int = 3) -> list[DocChunk]:
        self._ensure_built()
        if self._bm25 is None or not query.strip():
            return []
        scores = self._bm25.get_scores(_tokenize(query))
        ranked = sorted(zip(scores, self._chunks), key=lambda pair: pair[0], reverse=True)
        return [chunk for score, chunk in ranked[:k] if score > 0]


DOC_INDEX = _DocIndex()


# --------------------------------------------------------------------------- #
# Availability / client construction
# --------------------------------------------------------------------------- #


def has_api_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def chat_available() -> bool:
    """True when chat can actually run: API key set and required deps importable."""
    if not has_api_key():
        return False
    return all(importlib.util.find_spec(mod) is not None for mod in ("anthropic", "rank_bm25"))


def build_client() -> Any:
    """Construct the Anthropic client. Imported lazily so the no-key path (and the
    lean function that may lack the package) never imports anthropic."""
    import anthropic

    return anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment


# --------------------------------------------------------------------------- #
# The tool-use loop
# --------------------------------------------------------------------------- #


def _system_blocks(
    current_filters: dict[str, Any] | None,
    persona: str = DEFAULT_PERSONA,
) -> list[dict[str, Any]]:
    """System prompt as content blocks, ordered for prompt-cache reuse:

    1. the large shared core (marked ephemeral, so it caches and is reused even
       when the persona changes — the cached prefix stays identical),
    2. the short persona preamble (audience/tone — varies by persona),
    3. the small dynamic 'current view' block (varies per request).
    """
    persona_id = resolve_persona(persona)
    blocks: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": _SHARED_CORE,
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": PERSONAS[persona_id]["preamble"],
        },
    ]
    if current_filters:
        blocks.append(
            {
                "type": "text",
                "text": (
                    "Current dashboard view (for context; the user sees this now): "
                    + json.dumps(current_filters, default=str)
                ),
            }
        )
    return blocks


def _block_attr(block: Any, name: str, default: Any = None) -> Any:
    """Read an attribute from an SDK content block or a plain dict (test fakes)."""
    if isinstance(block, dict):
        return block.get(name, default)
    return getattr(block, name, default)


def run_chat_stream(
    messages: list[dict[str, Any]],
    *,
    client: Any,
    model: str = DEFAULT_MODEL,
    persona: str = DEFAULT_PERSONA,
    current_filters: dict[str, Any] | None = None,
    max_iterations: int = MAX_TOOL_ITERATIONS,
) -> Iterator[dict[str, Any]]:
    """Run the agentic tool-use loop, yielding events as they happen.

    This is the single source of truth for the loop; :func:`run_chat` drains it.

    ``messages`` is the conversation as ``[{"role", "content"}]`` (user/assistant,
    plain strings). ``client`` is any object exposing the Anthropic streaming
    surface — ``messages.stream(...)`` returning a context manager with a
    ``text_stream`` iterator and ``get_final_message()`` — injected so tests can
    pass a fake.

    Yields event dicts (consumed by the SSE route and the frontend):
    * ``{"type": "text", "text": <delta>}`` — a chunk of the assistant's reply.
    * ``{"type": "tool_call", "name", "args", "result_summary"}`` — an audit record.
    * ``{"type": "action", "action": {"type": "set_filters", "payload": {...}}}``.
    * ``{"type": "done"}`` — terminal event.
    """
    convo: list[dict[str, Any]] = [
        {"role": m["role"], "content": m["content"]}
        for m in messages[-MAX_CONTEXT_MESSAGES:]
    ]
    system = _system_blocks(current_filters, persona)
    # City the user is viewing — the per-request default for query_data. The
    # frontend sends Title Case ("London"); the data layer keys are lowercase.
    default_city = str((current_filters or {}).get("city") or DEFAULT_CITY).strip().lower()
    if default_city not in KNOWN_CITIES:
        default_city = DEFAULT_CITY

    for _ in range(max_iterations):
        with client.messages.stream(
            model=model,
            max_tokens=2048,
            system=system,
            tools=TOOLS,
            messages=convo,
        ) as stream:
            for delta in stream.text_stream:
                if delta:
                    yield {"type": "text", "text": delta}
            final = stream.get_final_message()

        content = list(final.content)
        tool_uses = [b for b in content if _block_attr(b, "type") == "tool_use"]
        if not tool_uses:
            break

        convo.append({"role": "assistant", "content": content})
        tool_results: list[dict[str, Any]] = []
        for tu in tool_uses:
            name = _block_attr(tu, "name")
            args = _block_attr(tu, "input") or {}
            result, action, summary = dispatch_tool(name, args, default_city=default_city)
            yield {"type": "tool_call", "name": name, "args": args, "result_summary": summary}
            if action is not None:
                yield {"type": "action", "action": action}
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": _block_attr(tu, "id"),
                    "content": json.dumps(result, default=str),
                }
            )
        convo.append({"role": "user", "content": tool_results})

    yield {"type": "done"}


def run_chat(
    messages: list[dict[str, Any]],
    *,
    client: Any,
    model: str = DEFAULT_MODEL,
    persona: str = DEFAULT_PERSONA,
    current_filters: dict[str, Any] | None = None,
    max_iterations: int = MAX_TOOL_ITERATIONS,
) -> dict[str, Any]:
    """Non-streaming convenience wrapper: drain :func:`run_chat_stream` into the
    assembled ``{"text", "actions", "tool_calls"}`` payload. Kept for tests and any
    caller that wants the whole reply at once."""
    text_parts: list[str] = []
    actions: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []

    for event in run_chat_stream(
        messages,
        client=client,
        model=model,
        persona=persona,
        current_filters=current_filters,
        max_iterations=max_iterations,
    ):
        kind = event.get("type")
        if kind == "text":
            text_parts.append(event["text"])
        elif kind == "tool_call":
            tool_calls.append(
                {
                    "name": event["name"],
                    "args": event["args"],
                    "result_summary": event["result_summary"],
                }
            )
        elif kind == "action":
            actions.append(event["action"])

    return {"text": "".join(text_parts).strip(), "actions": actions, "tool_calls": tool_calls}
