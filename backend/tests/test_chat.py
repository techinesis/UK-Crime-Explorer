"""Tests for the AI chat layer.

Three groups:

1. **Tool-call shapes** — the tool registry, filter normalisation, and each tool
   implementation (run against the real snapshotted data, like test_api).
2. **End-to-end** — the tool-use loop driven by a *mocked* Anthropic streaming
   client (canned text deltas + tool_use turns), exercising both the streaming
   generator (:func:`core.chat.run_chat_stream`) and the assembling wrapper
   (:func:`core.chat.run_chat`), the action protocol, and the audit trail —
   without any network call.
3. **HTTP** — the SSE route + persona + graceful 503.

The mocked client mimics the Anthropic streaming surface used by run_chat_stream:
``client.messages.stream(**kwargs)`` returns a context manager exposing a
``text_stream`` iterator and ``get_final_message()`` (a Message with ``content``
blocks). Content blocks are plain dicts, read via core.chat's dict/attr-agnostic
accessor.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core import chat as chat_core
from core.chat import (
    DEFAULT_FILTERS,
    PERSONAS,
    TOOLS,
    VALID_CATEGORIES,
    dispatch_tool,
    normalize_filters,
    resolve_persona,
    run_chat,
    run_chat_stream,
    tool_get_weights,
    tool_query_data,
    tool_set_filters,
)
from core.data import KNOWN_CITIES


# --------------------------------------------------------------------------- #
# A minimal fake Anthropic *streaming* client
# --------------------------------------------------------------------------- #


class _FakeStream:
    """One assistant turn: streams ``text_deltas`` then exposes a final message
    whose content is ``blocks`` (plain dicts)."""

    def __init__(self, text_deltas: list[str], blocks: list[dict]) -> None:
        self.text_stream = iter(text_deltas)
        self._final = SimpleNamespace(content=blocks, stop_reason="end_turn")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._final


class _FakeStreamMessages:
    def __init__(self, turns: list) -> None:
        self._turns = list(turns)
        self.calls: list[dict] = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        return self._turns.pop(0)


class FakeClient:
    """Returns canned streaming turns in order."""

    def __init__(self, turns: list) -> None:
        self.messages = _FakeStreamMessages(turns)


def _text_turn(text: str) -> _FakeStream:
    """A final-answer turn: streams the text (as two deltas) with a text block."""
    mid = max(1, len(text) // 2)
    return _FakeStream([text[:mid], text[mid:]], [{"type": "text", "text": text}])


def _tool_turn(tool_id: str, name: str, args: dict) -> _FakeStream:
    """A tool-use turn: no visible text, one tool_use block."""
    return _FakeStream([], [{"type": "tool_use", "id": tool_id, "name": name, "input": args}])


# --------------------------------------------------------------------------- #
# Tool registry shape
# --------------------------------------------------------------------------- #


def test_tool_registry_has_all_tools():
    names = {t["name"] for t in TOOLS}
    assert names == {
        "set_filters",
        "query_data",
        "get_weights",
        "read_docs",
        "get_forecast",
        "get_allocation",
    }


def test_every_tool_declares_a_valid_input_schema():
    for tool in TOOLS:
        assert tool["name"]
        assert tool["description"]
        schema = tool["input_schema"]
        assert schema["type"] == "object"
        assert "properties" in schema


def test_filter_tools_expose_the_map_request_fields():
    by_name = {t["name"]: t for t in TOOLS}
    props = by_name["set_filters"]["input_schema"]["properties"]
    assert {"categories", "tier", "year", "months", "borough", "level", "metric", "severity_basis"} <= set(props)
    # query_data adds a ranking size and read_docs requires a topic.
    assert "top_n" in by_name["query_data"]["input_schema"]["properties"]
    assert by_name["read_docs"]["input_schema"]["required"] == ["topic"]


# --------------------------------------------------------------------------- #
# Filter normalisation
# --------------------------------------------------------------------------- #


def test_normalize_filters_keeps_only_provided_keys():
    out = normalize_filters({"metric": "composite", "level": "borough"})
    assert out == {"metric": "composite", "level": "borough"}


def test_normalize_filters_handles_year_sentinels():
    assert normalize_filters({"year": "All years"}) == {"year": None}
    assert normalize_filters({"year": 2024}) == {"year": 2024}
    assert normalize_filters({"year": None}) == {"year": None}


def test_normalize_filters_rejects_bad_enums_and_months():
    with pytest.raises(ValueError):
        normalize_filters({"metric": "bogus"})
    with pytest.raises(ValueError):
        normalize_filters({"level": "country"})
    with pytest.raises(ValueError):
        normalize_filters({"severity_basis": "mode"})
    with pytest.raises(ValueError):
        normalize_filters({"months": [13]})


def test_normalize_filters_lowercases_and_validates_city():
    assert normalize_filters({"city": "Manchester"}) == {"city": "manchester"}
    assert normalize_filters({"city": "london"}) == {"city": "london"}
    with pytest.raises(ValueError, match="unknown city"):
        normalize_filters({"city": "Gotham"})


def test_normalize_filters_resolves_categories_case_insensitively():
    # Proper names in any case, plus data.police.uk slug forms, resolve to canonical.
    out = normalize_filters({"categories": ["robbery", "DRUGS", "bicycle-theft"]})
    assert out == {"categories": ["Robbery", "Drugs", "Bicycle theft"]}


def test_normalize_filters_rejects_invented_category_labels():
    # The bug class that blanked the map in demo testing: "Drug Offences" is not a
    # real label; the error names the valid list so the model can self-correct.
    with pytest.raises(ValueError, match="unknown categories"):
        normalize_filters({"categories": ["Drug Offences"]})


def test_normalize_filters_unwraps_single_element_borough_list():
    assert normalize_filters({"borough": ["Camden"]}) == {"borough": "Camden"}
    with pytest.raises(ValueError, match="single name"):
        normalize_filters({"borough": ["Camden", "Westminster"]})


def test_normalize_filters_resolves_tier_case_insensitively():
    # filter_crime_df matches tiers by exact equality, so "high" must become "High".
    assert normalize_filters({"tier": "high"}) == {"tier": "High"}
    assert normalize_filters({"tier": "All tiers"}) == {"tier": "All tiers"}
    with pytest.raises(ValueError, match="unknown tier"):
        normalize_filters({"tier": "extreme"})


# --------------------------------------------------------------------------- #
# Tool implementations (against the real snapshot)
# --------------------------------------------------------------------------- #


def test_set_filters_emits_a_partial_action():
    result, action, summary = tool_set_filters(
        {"categories": ["Robbery"], "borough": "Westminster", "year": 2024}
    )
    assert action == {
        "type": "set_filters",
        "payload": {"categories": ["Robbery"], "borough": "Westminster", "year": 2024},
    }
    assert result["applied"] == action["payload"]
    assert "Robbery" in summary


def test_query_data_ranks_boroughs_by_composite():
    result, action, summary = tool_query_data(
        {"metric": "composite", "level": "borough", "top_n": 5}
    )
    assert action is None  # query never changes the user's view
    assert result["level"] == "borough"
    assert result["metric"] == "composite"
    assert result["unit_count"] == 33

    top = result["top"]
    assert len(top) == 5
    # ranked descending and grounded (name + numeric value + crime count)
    values = [row["value"] for row in top]
    assert values == sorted(values, reverse=True)
    assert all(row["name"] for row in top)
    assert result["vmax"] >= 1.0
    assert "borough/composite" in summary


def test_query_data_defaults_to_unfiltered_view():
    result, _, _ = tool_query_data({"metric": "raw", "level": "borough"})
    assert result["filters_applied"] == DEFAULT_FILTERS | {"metric": "raw", "level": "borough"}


def test_query_data_uses_the_callers_default_city():
    # The dashboard's current city is the per-request default for queries.
    result, _, _ = tool_query_data({"metric": "raw", "level": "borough"}, default_city="manchester")
    assert result["filters_applied"]["city"] == "manchester"
    assert result["unit_count"] >= 1
    assert result["total_crime_count"] >= 1


def test_query_data_explicit_city_overrides_the_default():
    result, _, _ = tool_query_data(
        {"metric": "raw", "level": "borough", "city": "Liverpool"}, default_city="london"
    )
    assert result["filters_applied"]["city"] == "liverpool"


def test_filter_schema_enums_cities_and_categories():
    props = {t["name"]: t for t in TOOLS}["set_filters"]["input_schema"]["properties"]
    assert props["city"]["enum"] == list(KNOWN_CITIES)
    assert props["categories"]["items"]["enum"] == VALID_CATEGORIES


def test_set_filters_passes_a_validated_city_into_the_action():
    result, action, summary = tool_set_filters({"city": "Manchester"})
    assert action["payload"] == {"city": "manchester"}
    assert "city=manchester" in summary


def test_set_filters_resolves_borough_to_the_datas_exact_name():
    # "camden" / "tower hamlets" match nothing in filter_crime_df; the tool must
    # resolve them against the city's data before they reach the dashboard.
    _, action, _ = tool_set_filters({"borough": "camden"}, default_city="london")
    assert action["payload"]["borough"] == "Camden"
    _, action, _ = tool_set_filters({"borough": "tower hamlets"}, default_city="london")
    assert action["payload"]["borough"] == "Tower Hamlets"
    # The "All boroughs" sentinel passes through untouched.
    _, action, _ = tool_set_filters({"borough": "All boroughs"}, default_city="london")
    assert action["payload"]["borough"] == "All boroughs"


def test_unknown_borough_errors_with_the_valid_list():
    result, action, summary = dispatch_tool(
        "set_filters", {"borough": "Atlantis"}, default_city="london"
    )
    assert action is None
    assert "unknown borough" in result["error"]
    assert "Westminster" in result["error"]  # the valid list is offered for self-correction


def test_query_data_resolves_borough_case_insensitively():
    result, _, _ = tool_query_data(
        {"metric": "raw", "level": "lsoa", "borough": "camden"}, default_city="london"
    )
    assert result["filters_applied"]["borough"] == "Camden"
    assert result["total_crime_count"] > 0


def test_query_data_groups_by_category():
    # "Top 3 crime types in London in 2025" — the question that exposed the gap.
    result, action, summary = tool_query_data(
        {"year": 2025, "group_by": "category", "top_n": 3}
    )
    assert action is None
    assert result["group_by"] == "category"
    assert result["unit_count"] == 14  # all canonical categories present in 2025
    top = result["top"]
    assert len(top) == 3
    assert all(t["name"] in VALID_CATEGORIES for t in top)
    values = [t["value"] for t in top]
    assert values == sorted(values, reverse=True)
    assert summary.startswith("category/raw: top 3")


def test_query_data_groups_by_year_and_month():
    # No top_n: time dimensions default to the WHOLE series (a top-5 default
    # would surface the five biggest years and hide the recent window).
    years, _, _ = tool_query_data({"group_by": "year"})
    year_ids = {t["id"] for t in years["top"]}
    assert "2024" in year_ids and "2025" in year_ids and "2008" in year_ids
    assert "2020" not in year_ids  # the 2017-2022 coverage gap

    # 2015 is a complete Kaggle year; the 2023+ window has missing months
    # (e.g. 2024 lacks Sep/Oct), so the calendar assertion uses 2015.
    months, _, _ = tool_query_data({"year": 2015, "group_by": "month", "top_n": 12})
    assert months["unit_count"] == 12
    assert {t["id"] for t in months["top"]} == {str(m) for m in range(1, 13)}


def test_query_data_hints_available_months_for_a_gappy_year():
    # The recent-window snapshot starts in May 2023, so 2023 is present but gappy:
    # Jan-Apr are missing while May-Dec are covered. Querying a missing month returns
    # an empty result, and the hint names which months of 2023 ARE covered.
    result, _, _ = tool_query_data({"year": 2023, "months": [2], "group_by": "category"})
    assert result["total_crime_count"] == 0
    hint = result["hint"]
    assert 2 not in hint["available_months_in_year"]
    assert 5 in hint["available_months_in_year"]


def test_query_data_empty_result_carries_an_available_years_hint():
    # A year inside the 2017-2022 gap must explain itself, not look like an outage.
    result, _, summary = tool_query_data({"year": 2020, "group_by": "category"})
    assert result["total_crime_count"] == 0
    assert result["top"] == []
    hint = result["hint"]
    assert 2024 in hint["available_years"]
    assert 2020 not in hint["available_years"]
    assert "no rows matched" in summary


def test_category_grouping_without_recent_year_carries_the_coverage_note():
    # 2008-2016 rows are one 'Other crime' bucket per LSOA-month; an all-years
    # category ranking must warn the model, a 2025-scoped one must not.
    all_years, _, _ = tool_query_data({"group_by": "category"})
    assert "2023" in all_years["note"]
    recent, _, _ = tool_query_data({"group_by": "category", "year": 2025})
    assert "note" not in recent


def test_category_filter_on_a_precategory_year_hints_coverage():
    # "Robbery in 2015" matches nothing (2015 has no category detail at all).
    result, _, _ = tool_query_data({"categories": ["Robbery"], "year": 2015})
    assert result["total_crime_count"] == 0
    assert "category_coverage" in result["hint"]


def test_query_data_rejects_unknown_group_by():
    result, action, _ = dispatch_tool("query_data", {"group_by": "constellation"})
    assert action is None
    assert "unknown group_by" in result["error"]


def test_group_by_schema_is_on_query_data_only():
    by_name = {t["name"]: t for t in TOOLS}
    assert "group_by" in by_name["query_data"]["input_schema"]["properties"]
    assert "group_by" not in by_name["set_filters"]["input_schema"]["properties"]


# --------------------------------------------------------------------------- #
# Drift guards: constants that future features must keep in sync with the data
# --------------------------------------------------------------------------- #


def test_known_cities_all_have_committed_snapshots():
    """Adding a city to KNOWN_CITIES without shipping its snapshot would break
    the chat in production (no live fetch there); catch it at test time."""
    from core.data import DEFAULT_CITY
    from core.paths import crime_snapshot

    assert DEFAULT_CITY in KNOWN_CITIES
    for city in KNOWN_CITIES:
        assert crime_snapshot(city).exists(), f"missing snapshot for {city!r}"


def test_valid_categories_match_the_weights_table():
    """The tool-schema category enum must track category_weights.csv; if a new
    category lands in one place but not the other, the chat would either reject
    a real label or offer one with no weights."""
    from core.weights import weights_records

    weights_categories = {row["category"] for row in weights_records()}
    assert set(VALID_CATEGORIES) == weights_categories


def test_get_weights_returns_the_full_anchored_table():
    result, action, summary = tool_get_weights({})
    assert action is None
    rows = result["categories"]
    assert len(rows) == 14
    assert all("preventability_anchor" in row for row in rows)


def test_read_docs_surfaces_literature_anchors_for_preventability():
    pytest.importorskip("rank_bm25")
    result, action, summary = dispatch_tool("read_docs", {"topic": "how is preventability calculated"})
    assert action is None
    chunks = result["chunks"]
    assert chunks, "expected at least one documentation chunk"
    blob = " ".join(chunk["text"] for chunk in chunks)
    # The literature anchors live in PREVENTABILITY_14 / the docs corpus.
    assert "Weisburd" in blob or "Braga" in blob


def test_read_docs_surfaces_the_lp_allocation_methodology():
    # Phase 3 added the allocation model docstrings to the BM25 corpus so methodology
    # questions about the LP are answered from source rather than improvised.
    pytest.importorskip("rank_bm25")
    result, action, _ = dispatch_tool(
        "read_docs", {"topic": "lp allocation linear program objective equity floor"}
    )
    assert action is None
    chunks = result["chunks"]
    assert chunks, "expected at least one documentation chunk"
    assert "allocation/__init__.py" in {c["source"] for c in chunks}


def test_dispatch_unknown_tool_returns_error_not_crash():
    result, action, summary = dispatch_tool("teleport", {})
    assert action is None
    assert "error" in result


def test_dispatch_tool_catches_tool_errors():
    # A bad enum inside set_filters should be reported, not raised.
    result, action, summary = dispatch_tool("set_filters", {"metric": "bogus"})
    assert action is None
    assert "error" in result


# --------------------------------------------------------------------------- #
# get_forecast (reads the committed forecast file)
# --------------------------------------------------------------------------- #


def test_get_forecast_ranks_boroughs_by_predicted_crimes():
    result, action, summary = dispatch_tool(
        "get_forecast", {"city": "london", "group_by": "borough", "top_n": 5}
    )
    assert action is None
    assert set(result) == {"rows", "filters", "total_predicted", "n_rows_after_filter"}
    rows = result["rows"]
    assert 1 <= len(rows) <= 5
    values = [r["predicted_crimes"] for r in rows]
    assert values == sorted(values, reverse=True)  # ranked descending
    assert all(r["key"] for r in rows)
    assert result["total_predicted"] > 0
    assert result["n_rows_after_filter"] > 0
    assert result["filters"]["group_by"] == "borough"


def test_get_forecast_empty_filter_spans_the_whole_horizon():
    result, _, _ = dispatch_tool("get_forecast", {})
    assert result["n_rows_after_filter"] > 0
    assert result["total_predicted"] > 0
    assert result["filters"]["group_by"] == "lsoa"  # schema default


def test_get_forecast_unknown_city_returns_error_not_raise():
    result, action, summary = dispatch_tool("get_forecast", {"city": "atlantis"})
    assert action is None
    assert "error" in result
    assert "atlantis" in result["error"]


def test_get_forecast_unknown_category_returns_no_rows():
    result, _, _ = dispatch_tool(
        "get_forecast", {"category": "Not A Real Category", "group_by": "category"}
    )
    assert result["rows"] == []
    assert result["n_rows_after_filter"] == 0
    assert result["total_predicted"] == 0.0


def test_get_forecast_filters_by_borough_and_month():
    # The spec's headline demo shape: a borough + a forecast month, ranked by LSOA.
    # 2026-04 is the first month of the committed 1-year forecast horizon.
    result, _, _ = dispatch_tool(
        "get_forecast",
        {"borough": "Camden", "month": "2026-04", "group_by": "lsoa", "top_n": 5},
    )
    rows = result["rows"]
    assert rows, "Camden should have forecast LSOAs in 2026-04"
    assert len(rows) <= 5
    values = [r["predicted_crimes"] for r in rows]
    assert values == sorted(values, reverse=True)
    assert result["filters"]["borough"] == "Camden"
    assert result["filters"]["month"] == "2026-04"


# --------------------------------------------------------------------------- #
# get_allocation (calls the shared allocation pipeline)
# --------------------------------------------------------------------------- #

# The default total_units (33000, matching the dashboard's DEFAULT_FILTERS.totalUnits)
# is above the min-units feasibility floor (6 * ~5160 LSOAs = 30960), so the default
# LP/Rawls solve returns a real ranking. A deliberately low total_units stays below the
# floor to exercise the infeasible-warning path.
_INFEASIBLE_UNITS = 10000


def test_get_allocation_averaging_ranks_boroughs():
    result, action, summary = dispatch_tool(
        "get_allocation", {"model": "averaging", "group_by": "borough", "top_n": 5}
    )
    assert action is None
    assert set(result) == {"rows", "model", "total_units", "infeasible_warning"}
    assert result["model"] == "averaging"
    assert result["infeasible_warning"] is None
    rows = result["rows"]
    assert 1 <= len(rows) <= 5
    units = [r["units"] for r in rows]
    assert units == sorted(units, reverse=True)  # ranked descending
    assert all(r["key"] and "share" in r for r in rows)


def test_get_allocation_lp_ranks_boroughs_at_the_default():
    result, _, _ = dispatch_tool(
        "get_allocation", {"model": "lp", "group_by": "borough", "top_n": 33}
    )
    assert result["model"] == "lp"
    assert result["infeasible_warning"] is None
    units = [r["units"] for r in result["rows"]]
    assert len(units) > 1
    assert units == sorted(units, reverse=True)


def test_get_allocation_rawls_ranks_boroughs_at_the_default():
    result, _, _ = dispatch_tool(
        "get_allocation", {"model": "rawls", "group_by": "borough", "top_n": 33}
    )
    assert result["model"] == "rawls"
    assert result["infeasible_warning"] is None
    assert len(result["rows"]) > 1


def test_get_allocation_lp_and_rawls_rankings_diverge():
    lp, _, _ = dispatch_tool(
        "get_allocation", {"model": "lp", "group_by": "borough", "top_n": 33}
    )
    rawls, _, _ = dispatch_tool(
        "get_allocation", {"model": "rawls", "group_by": "borough", "top_n": 33}
    )
    lp_units = {r["key"]: r["units"] for r in lp["rows"]}
    rawls_units = {r["key"]: r["units"] for r in rawls["rows"]}
    diverging = [b for b in lp_units if abs(lp_units[b] - rawls_units.get(b, 0.0)) > 1.0]
    assert diverging, "LP and Rawls should not produce identical allocations"


def test_get_allocation_default_total_units_is_feasible():
    # The default (33000) is above the feasibility floor, so the default LP answer is a
    # real borough ranking — the spec's Phase 2 acceptance criterion.
    result, action, _ = dispatch_tool("get_allocation", {"model": "lp", "group_by": "borough"})
    assert action is None
    assert result["total_units"] == 33000
    assert result["infeasible_warning"] is None
    assert len(result["rows"]) > 1


def test_get_allocation_infeasibly_low_total_units_warns():
    # Below the min-units floor both LP and Rawls are infeasible; the tool must surface a
    # warning with no rows, never raise (Rawls used to crash with a TypeError here).
    for model in ("lp", "rawls"):
        result, action, _ = dispatch_tool(
            "get_allocation",
            {"model": model, "total_units": _INFEASIBLE_UNITS, "group_by": "borough"},
        )
        assert action is None
        assert result["rows"] == []
        assert result["infeasible_warning"]


def test_get_allocation_non_london_city_returns_error():
    result, action, _ = dispatch_tool("get_allocation", {"city": "manchester"})
    assert action is None
    assert "error" in result


# --------------------------------------------------------------------------- #
# Personas
# --------------------------------------------------------------------------- #


def test_resolve_persona_maps_known_and_defaults_unknown():
    assert resolve_persona("examiner") == "examiner"
    assert resolve_persona("COMMUNITY") == "community"
    assert resolve_persona(None) == "police"
    assert resolve_persona("nonsense") == "police"


def test_shared_core_keeps_the_deployment_guardrail():
    # Phase 3 wires forecast/allocation tools in, but the deployment guardrail must
    # survive verbatim: the assistant ranks and explains; a human planner decides.
    # Whitespace is normalised so line-wrapping in the prompt doesn't hide the phrase.
    core = " ".join(chat_core._SHARED_CORE.lower().split())
    assert "planner" in core
    assert "never give an officer count" in core
    assert "deploy n here" in core
    # The guardrail rides on the shared core, so every persona inherits it.
    for persona in PERSONAS:
        blocks = chat_core._system_blocks(None, persona)
        assert blocks[0]["text"] == chat_core._SHARED_CORE


def test_shared_core_advertises_forecast_and_allocation_tools():
    # Inverted from the pre-Phase-3 guardrail: the "those tools are not connected to
    # you yet" hedge is gone now that get_forecast / get_allocation are wired, and the
    # new "you CAN look up" wording is present on every persona's shared core.
    core = " ".join(chat_core._SHARED_CORE.lower().split())
    assert "not connected to you yet" not in core
    assert "cannot forecast future crime" not in core
    assert "you can look up forecast figures and allocation rankings" in core
    for persona in PERSONAS:
        blocks = chat_core._system_blocks(None, persona)
        assert blocks[0]["text"] == chat_core._SHARED_CORE


def test_system_blocks_swap_persona_but_keep_a_stable_cached_core():
    police = chat_core._system_blocks(None, "police")
    examiner = chat_core._system_blocks(None, "examiner")
    # First block is the shared core, marked for prompt caching, identical across
    # personas (so switching persona still hits the cache).
    assert police[0]["cache_control"] == {"type": "ephemeral"}
    assert police[0]["text"] == examiner[0]["text"]
    # Second block is the persona preamble — and it differs.
    assert police[1]["text"] == PERSONAS["police"]["preamble"]
    assert examiner[1]["text"] == PERSONAS["examiner"]["preamble"]
    assert police[1]["text"] != examiner[1]["text"]


# --------------------------------------------------------------------------- #
# End-to-end loop against a mocked streaming LLM
# --------------------------------------------------------------------------- #


def test_run_chat_query_flow_returns_grounded_text_and_audit():
    client = FakeClient(
        [
            _tool_turn("t1", "query_data", {"metric": "composite", "level": "borough", "top_n": 5}),
            _text_turn("The top five boroughs by composite demand are listed above."),
        ]
    )
    result = run_chat(
        [{"role": "user", "content": "Which five boroughs have the highest preventable harm?"}],
        client=client,
    )

    assert result["text"] == "The top five boroughs by composite demand are listed above."
    assert result["actions"] == []  # a query produces no dashboard action
    assert len(result["tool_calls"]) == 1
    call = result["tool_calls"][0]
    assert call["name"] == "query_data"
    assert "borough/composite" in call["result_summary"]

    # The loop ran twice: tool_use round, then the final text round, and the
    # second request carried a tool_result back to the model.
    assert len(client.messages.calls) == 2
    follow_up = client.messages.calls[1]["messages"][-1]
    assert follow_up["role"] == "user"
    assert follow_up["content"][0]["type"] == "tool_result"


def test_run_chat_set_filters_flow_produces_an_action():
    client = FakeClient(
        [
            _tool_turn("t2", "set_filters", {"categories": ["Robbery"], "borough": "Westminster", "year": 2024}),
            _text_turn("Done — the map now shows robbery in Westminster for 2024."),
        ]
    )
    result = run_chat(
        [{"role": "user", "content": "Show me robbery in Westminster in 2024"}],
        client=client,
    )

    assert result["actions"] == [
        {
            "type": "set_filters",
            "payload": {"categories": ["Robbery"], "borough": "Westminster", "year": 2024},
        }
    ]
    assert result["tool_calls"][0]["name"] == "set_filters"
    assert "robbery" in result["text"].lower()


def test_run_chat_caps_context_to_recent_messages():
    client = FakeClient([_text_turn("ok")])
    long_history = [{"role": "user", "content": f"msg {i}"} for i in range(40)]
    run_chat(long_history, client=client)
    sent = client.messages.calls[0]["messages"]
    assert len(sent) == chat_core.MAX_CONTEXT_MESSAGES


# --------------------------------------------------------------------------- #
# Streaming generator: event sequence
# --------------------------------------------------------------------------- #


def test_stream_query_flow_emits_text_then_tool_call_then_done():
    client = FakeClient(
        [
            _tool_turn("t1", "query_data", {"metric": "composite", "level": "borough", "top_n": 5}),
            _text_turn("Westminster leads."),
        ]
    )
    events = list(
        run_chat_stream([{"role": "user", "content": "top boroughs?"}], client=client)
    )
    kinds = [e["type"] for e in events]

    assert kinds[-1] == "done"  # terminal event
    assert "tool_call" in kinds
    assert "action" not in kinds  # query_data never yields an action
    # Reassembling the text deltas gives the final answer.
    text = "".join(e["text"] for e in events if e["type"] == "text")
    assert text == "Westminster leads."
    tool_call = next(e for e in events if e["type"] == "tool_call")
    assert tool_call["name"] == "query_data"


def test_stream_set_filters_flow_emits_action_before_done():
    client = FakeClient(
        [
            _tool_turn("t2", "set_filters", {"categories": ["Robbery"], "borough": "Westminster"}),
            _text_turn("Showing robbery in Westminster."),
        ]
    )
    events = list(
        run_chat_stream([{"role": "user", "content": "show robbery in westminster"}], client=client)
    )
    kinds = [e["type"] for e in events]

    assert kinds[-1] == "done"
    assert kinds.index("action") < kinds.index("done")  # action arrives before done
    action = next(e for e in events if e["type"] == "action")
    assert action["action"] == {
        "type": "set_filters",
        "payload": {"categories": ["Robbery"], "borough": "Westminster"},
    }


def test_stream_passes_persona_into_the_system_prompt():
    client = FakeClient([_text_turn("hi")])
    list(run_chat_stream([{"role": "user", "content": "hello"}], client=client, persona="examiner"))
    system = client.messages.calls[0]["system"]
    assert system[1]["text"] == PERSONAS["examiner"]["preamble"]


def test_stream_threads_the_current_view_city_into_tool_dispatch(monkeypatch):
    """The frontend sends Title-case city in current_filters; query_data must
    receive it lowercased as its default."""
    captured: dict = {}

    def fake_dispatch(name, args, *, default_city="london"):
        captured["name"] = name
        captured["default_city"] = default_city
        return {"ok": True}, None, "stub"

    monkeypatch.setattr(chat_core, "dispatch_tool", fake_dispatch)
    client = FakeClient(
        [
            _tool_turn("t1", "query_data", {"metric": "raw", "level": "borough"}),
            _text_turn("done"),
        ]
    )
    list(
        run_chat_stream(
            [{"role": "user", "content": "top boroughs?"}],
            client=client,
            current_filters={"city": "Manchester", "level": "borough"},
        )
    )
    assert captured == {"name": "query_data", "default_city": "manchester"}


def test_stream_falls_back_to_london_for_unknown_current_city(monkeypatch):
    captured: dict = {}

    def fake_dispatch(name, args, *, default_city="london"):
        captured["default_city"] = default_city
        return {"ok": True}, None, "stub"

    monkeypatch.setattr(chat_core, "dispatch_tool", fake_dispatch)
    client = FakeClient([_tool_turn("t1", "query_data", {}), _text_turn("done")])
    list(
        run_chat_stream(
            [{"role": "user", "content": "hi"}],
            client=client,
            current_filters={"city": "Atlantis"},
        )
    )
    assert captured["default_city"] == "london"


# --------------------------------------------------------------------------- #
# HTTP layer (SSE route + persona + graceful degradation)
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def http_client():
    pytest.importorskip("slowapi")
    from fastapi.testclient import TestClient

    from api.main import app

    with TestClient(app) as client:
        yield client


def _parse_sse(body: str) -> list[dict]:
    import json

    events = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            events.append(json.loads(line[len("data:") :].strip()))
    return events


def test_health_reports_unconfigured_without_a_key(http_client, monkeypatch):
    monkeypatch.setattr(chat_core, "chat_available", lambda: False)
    body = http_client.get("/api/chat/health").json()
    assert body == {"configured": False}


def test_chat_returns_503_when_not_configured(http_client, monkeypatch):
    monkeypatch.setattr(chat_core, "chat_available", lambda: False)
    res = http_client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert res.status_code == 503
    assert res.json() == {"error": "AI chat is not configured"}


def test_chat_streams_sse_events_over_http_with_mocked_client(http_client, monkeypatch):
    monkeypatch.setattr(chat_core, "chat_available", lambda: True)
    monkeypatch.setattr(
        chat_core,
        "build_client",
        lambda: FakeClient(
            [
                _tool_turn("t1", "get_weights", {}),
                _text_turn("Preventability is a literature-anchored multiplier."),
            ]
        ),
    )

    res = http_client.post(
        "/api/chat",
        json={
            "messages": [{"role": "user", "content": "How is preventability calculated?"}],
            "persona": "examiner",
        },
    )
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(res.text)
    kinds = [e["type"] for e in events]
    assert kinds[-1] == "done"
    text = "".join(e["text"] for e in events if e["type"] == "text")
    assert text == "Preventability is a literature-anchored multiplier."
    tool_call = next(e for e in events if e["type"] == "tool_call")
    assert tool_call["name"] == "get_weights"
    assert "action" not in kinds
