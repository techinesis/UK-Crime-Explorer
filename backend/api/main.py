"""FastAPI app: meta, map, and weights endpoints.

The crime DataFrame is loaded once and held for the process lifetime (and reused
across warm serverless invocations). /api/map results are memoised on the filter
tuple. Boundary GeoJSON is served as static CDN assets, not by this API.
"""

from __future__ import annotations
from typing import no_type_check

from contextlib import asynccontextmanager
from functools import lru_cache

import numpy as np
from allocation import (
    _DAILY_HOURLY_WEIGHTS,
    AllocationInfeasibleError,
    AveragingModel,
    LPModel,
    RawlsModel,
)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core import geometry
from core.composite import compute_map_values
from core.data import (
    BOROUGH_ALL,
    ID_COLUMN_BY_LEVEL,
    TIER_ALL,
    aggregate,
    filter_crime_df,
    get_crime_long,
    get_forecast_long,
)
from core.weights import category_metadata, load_weights, weights_records
from api.chat import register_chat
from api.schemas import (
    AllocationResponse,
    CategoryMeta,
    MapRequest,
    MapResponse,
    MetaResponse,
    AllocationEntry,
)

ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

TIERS = ["All tiers", "High", "Medium", "Low"]

# Built once at startup from the loaded crime frame + weights.
_META_CACHE: dict[str, object] = {}


def _build_meta(city: str) -> MetaResponse:
    df = get_crime_long(city)
    years = sorted(int(y) for y in df["year"].dropna().unique())
    months = sorted(int(m) for m in df["month"].dropna().unique())
    boroughs = sorted(str(b) for b in df["borough"].dropna().unique())
    data_categories = sorted(str(c) for c in df["category"].dropna().unique())

    period_pairs = (
        df[["year", "month"]].dropna().drop_duplicates().astype(int)
    )
    periods = sorted((int(y), int(m)) for y, m in period_pairs.itertuples(index=False, name=None))

    # Metadata from the weights CSV; categories present in the data but absent
    # from weights get the same conservative defaults app.py applies. (Convert
    # the core dataclass to the API schema type.)
    meta_by_name = {m.name: m for m in category_metadata()}
    categories = []
    for name in data_categories:
        src = meta_by_name.get(name)
        if src is not None:
            categories.append(
                CategoryMeta(
                    name=src.name,
                    preventability_tier=src.preventability_tier,
                    preventability_confidence=src.preventability_confidence,
                    preventability_anchor=src.preventability_anchor,
                )
            )
        else:
            categories.append(
                CategoryMeta(
                    name=name,
                    preventability_tier="Low",
                    preventability_confidence="Low",
                    preventability_anchor="(no anchor)",
                )
            )
    return MetaResponse(
        years=years,
        months=months,
        periods=periods,
        categories=categories,
        boroughs=boroughs,
        tiers=TIERS,
        city=city,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm the crime frame, weights, and meta before serving. (Harmless if the
    # serverless adapter skips lifespan — the lru_caches lazy-load on first use.)
    city = "london"
    get_crime_long(city)
    load_weights()
    _META_CACHE[f"meta-{city}"] = _build_meta(city)
    yield


app = FastAPI(title="London Crime Explorer API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Mount the AI chat router (POST /api/chat, GET /api/chat/health) on the same app
# so it shares the CORS config above. Self-disables gracefully when the chat is
# not configured (no API key / deps), leaving the rest of the API untouched.
register_chat(app)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/meta", response_model=MetaResponse)
def meta(city: str = "london") -> MetaResponse:
    return _META_CACHE.get(f"meta-{city}") or _build_meta(city)


@lru_cache(maxsize=512)
def _map_payload(
    categories: tuple[str, ...],
    tier: str,
    year: int | None,
    months: tuple[int, ...],
    borough: str,
    level: str,
    metric: str,
    severity_basis: str,
    city: str,
) -> dict:
    df = get_crime_long(city)
    filtered = filter_crime_df(
        df, categories=categories, tier=tier, year=year, months=months, borough=borough
    )
    aggregated = aggregate(filtered, level)

    # Reindex to every unit at the level, 0-filling empties so they still appear
    # (matches the boundary left-join in app.py).
    id_col = ID_COLUMN_BY_LEVEL[level]
    all_ids = geometry.unit_ids(level)
    aggregated = (
        aggregated.set_index(id_col)
        .reindex(all_ids)
        .fillna(0.0)
        .rename_axis(id_col)
        .reset_index()
    )

    values, vmin, vmax = compute_map_values(aggregated, metric, severity_basis)
    ids = aggregated[id_col].astype(str).tolist()
    return {
        "values": {i: float(v) for i, v in zip(ids, values)},
        "crime_counts": {
            i: float(c) for i, c in zip(ids, aggregated["crime_count"])
        },
        "vmin": vmin,
        "vmax": vmax,
    }


@app.post("/api/map", response_model=MapResponse)
def map_values(req: MapRequest) -> MapResponse:
    payload = _map_payload(
        tuple(req.categories),
        req.tier or TIER_ALL,
        req.year,
        tuple(req.months),
        req.borough or BOROUGH_ALL,
        req.level,
        req.metric,
        req.severity_basis,
        req.city,
    )
    return MapResponse(**payload)


@app.get("/api/weights")
def weights() -> list[dict]:
    return weights_records()


_CAT_TEMPLATES: dict[str, np.ndarray] = {}
for _cat, (_hw, _dw) in _DAILY_HOURLY_WEIGHTS.items():
    _h = np.array(_hw, dtype=float)
    _h /= _h.sum()
    _d = np.array(_dw, dtype=float)
    _d /= _d.sum()
    _CAT_TEMPLATES[_cat] = np.outer(_d, _h)

_DEFAULT_TEMPLATE = _CAT_TEMPLATES.get("Other crime", np.ones((7, 24)) / (7 * 24))


def _lsoa_weekly_schedule(crime_shares: dict, units: int, active: float = 0.33) -> list[list[int]]:
    total = sum(crime_shares.values())
    if total <= 0:
        return [[1] * 24 for _ in range(7)]
    template = np.zeros((7, 24), dtype=float)
    for cat, count in crime_shares.items():
        template += (count / total) * _CAT_TEMPLATES.get(cat, _DEFAULT_TEMPLATE)
    mean_val = template.mean()
    if mean_val > 0:
        template /= mean_val
    return np.maximum(np.round(template * units * active).astype(int), 1).tolist()


@no_type_check # type checkers aren't too happy about itertuples
@lru_cache(maxsize=64)
def _allocation_payload(
    city: str,
    total_units: int,
    model: str,
    alpha: float,
    beta: float,
    max_cap_factor: float,
    equity_floor: float,
    min_units_per_lsoa: int,
) -> AllocationResponse:
    df = get_forecast_long(city)
    resp = AllocationResponse(
        city=city,
        total_units=total_units,
        model=model,
        warning="",
        entries=[],
    )

    lsoa_name_map = df.groupby("lsoa_code")["lsoa_name"].first()
    borough_map = df.groupby("lsoa_code")["borough"].first()

    warning: str | None = None
    if model == "lp":
        alloc_model = LPModel(
            weighted_column="composite_weighted_mean",
            total_units=total_units,
            alpha=alpha,
            beta=beta,
            gamma=max(0.0, 1.0 - alpha - beta),
            max_cap_factor=max_cap_factor,
            equity_floor=equity_floor,
            min_units_per_lsoa=min_units_per_lsoa,
        )
    elif model == "rawls":
        alloc_model = RawlsModel(
            weighted_column="composite_weighted_mean",
            total_units=total_units,
            min_units_per_lsoa=min_units_per_lsoa,
        )
    else:
        alloc_model = AveragingModel(total_units=total_units)

    try:
        allocated_df = alloc_model.allocate(df)
    except AllocationInfeasibleError as e:
        warning = f"Allocation was infeasible with the given parameters ({e})."
        resp.warning = warning
        return resp

    allocated_df["lsoa_name"] = (
        allocated_df["lsoa_code"].map(lsoa_name_map).fillna(allocated_df["lsoa_code"])
    )
    if "borough" not in allocated_df.columns:
        allocated_df["borough"] = allocated_df["lsoa_code"].map(borough_map)

    crime_by_lsoa: dict[str, dict[str, float]] = {}
    for row in (
        df
        .groupby(["lsoa_code", "category"])["crime_count"]
        .sum()
        .reset_index()
        .itertuples(index=False)
    ):
        crime_by_lsoa.setdefault(str(row.lsoa_code), {})[str(row.category)] = float(row.crime_count)

    entries = []
    for row in allocated_df.itertuples(index=False):
        lsoa = str(row.lsoa_code)
        u = max(1, int(round(float(row.units))))
        shares = crime_by_lsoa.get(lsoa, {"Other crime": 1.0})
        entries.append(
            AllocationEntry(
                lsoa_code=lsoa,
                lsoa_name=str(row.lsoa_name),
                borough=str(row.borough),
                units=float(row.units),
                schedule=_lsoa_weekly_schedule(shares, u),
            )
        )

    resp.warning = warning
    resp.entries = entries
    return resp


@app.get("/api/allocation", response_model=AllocationResponse)
def allocation_endpoint(
    # Not sure if there is a way to put these into a class while preserving defaults
    city: str = "london",
    total_units: int = 30000,
    model: str = "lp",
    alpha: float = 0.6,
    beta: float = 0.25,
    max_cap_factor: float = 2.0,
    equity_floor: float = 0.7,
    min_units_per_lsoa: int = 6,
) -> AllocationResponse:
    if city != "london":
        raise NotImplementedError("Allocation is currently only supported for London")
    return _allocation_payload(
        city, total_units, model, alpha, beta, max_cap_factor, equity_floor, min_units_per_lsoa
    )
