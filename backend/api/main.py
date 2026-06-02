"""FastAPI app: meta, map, and weights endpoints.

The crime DataFrame is loaded once and held for the process lifetime (and reused
across warm serverless invocations). /api/map results are memoised on the filter
tuple. Boundary GeoJSON is served as static CDN assets, not by this API.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from functools import lru_cache

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
)
from core.weights import category_metadata, load_weights, weights_records
from api.chat import register_chat
from api.schemas import CategoryMeta, MapRequest, MapResponse, MetaResponse

ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

TIERS = ["All tiers", "High", "Medium", "Low"]

# Built once at startup from the loaded crime frame + weights.
_META_CACHE: dict[str, object] = {}


def _build_meta() -> MetaResponse:
    df = get_crime_long()
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
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm the crime frame, weights, and meta before serving. (Harmless if the
    # serverless adapter skips lifespan — the lru_caches lazy-load on first use.)
    get_crime_long()
    load_weights()
    _META_CACHE["meta"] = _build_meta()
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
def meta() -> MetaResponse:
    return _META_CACHE.get("meta") or _build_meta()


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
) -> dict:
    df = get_crime_long()
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
    )
    return MapResponse(**payload)


@app.get("/api/weights")
def weights() -> list[dict]:
    return weights_records()
