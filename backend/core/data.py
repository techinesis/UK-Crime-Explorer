"""Crime data: load, filter, aggregate.

Wraps ``api.client.Client.street_crimes_timerange`` with the exact arguments
the original Streamlit ``app.py`` used, then reproduces the weight/ward merges
and composite-column computation from ``load_data()``. A parquet snapshot of
the raw client output makes restarts fast and offline.
"""

from __future__ import annotations

from functools import lru_cache

import pandas as pd

from core.composite import METRIC_COLUMNS, add_composite_columns
from core.paths import crime_snapshot, LSOA_TO_WARD_CSV
from core.weights import load_weights

# Exact data-load arguments lifted from app.py:298-312. Do not change without a
# matching change to the analysis methodology.
TIMERANGE_START_YEAR = 2023
TIMERANGE_END_YEAR = None  # -> resolved to data.police.uk's last-updated month
TIMERANGE_EXCLUDE_YEAR_MONTH = [
    "2023-01",
    "2023-02",
    "2023-03",
    "2023-04",
    "2023-05",
    "2024-09",
    "2024-10",
    "2025-03",
    "2025-11",
]

RAW_COLUMNS = ["lsoa_code", "lsoa_name", "borough", "category", "year", "month", "crime_count"]

ID_COLUMN_BY_LEVEL: dict[str, str] = {
    "lsoa": "lsoa_code",
    "ward": "ward_code",
    "borough": "borough",
}

# Sentinels accepted from the frontend meaning "no filter on this dimension".
TIER_ALL = "All tiers"
YEAR_ALL = "All years"
BOROUGH_ALL = "All boroughs"

# The preventability tiers as stored in the data (derived from the multiplier in
# prepare_category_weights.py), plus the "no filter" sentinel.
TIERS: tuple[str, ...] = (TIER_ALL, "High", "Medium", "Low")

# Cities served by the per-city snapshots (data/crime_snapshot-<city>.parquet).
# Mirrors api/client.Client.__city_meta, which cannot be imported here at module
# scope (client.py loads the LSOA boundaries at import time — see _fetch_raw_crime).
DEFAULT_CITY = "london"
KNOWN_CITIES: tuple[str, ...] = ("london", "birmingham", "manchester", "liverpool")

# Canonicalize crime-category labels to the 14 proper names. The assembled data
# historically carried three spellings of the same categories: the proper names
# (from the Kaggle 2008-2016 mapping), raw data.police.uk slugs from older cached
# monthly extracts, and two typos ("Robber", "Posession of weapons") baked into
# an earlier client.py marker mapping. Collapsing them gives /api/meta a clean
# 14-item list and stops counts being split across duplicate labels. Applied
# before the weights merge so the names line up with category_weights.csv.
CANONICAL_CATEGORY: dict[str, str] = {
    # data.police.uk slugs -> proper names
    "anti-social-behaviour": "Anti-social behaviour",
    "bicycle-theft": "Bicycle theft",
    "burglary": "Burglary",
    "criminal-damage-arson": "Criminal damage and arson",
    "drugs": "Drugs",
    "other-crime": "Other crime",
    "other-theft": "Other theft",
    "possession-of-weapons": "Possession of weapons",
    "public-order": "Public order",
    "robbery": "Robbery",
    "shoplifting": "Shoplifting",
    "theft-from-the-person": "Theft from the person",
    "vehicle-crime": "Vehicle crime",
    "violent-crime": "Violence and sexual offences",
    # legacy typos that reached the data before client.py was corrected
    "Robber": "Robbery",
    "Posession of weapons": "Possession of weapons",
}


def _fetch_raw_crime(city: str) -> pd.DataFrame:
    """Fetch the raw long crime DataFrame from the data client (may hit the
    network for uncached months and the last-updated lookup)."""
    # Imported lazily: api.client loads the LSOA boundaries at import time, and
    # only the fetch path needs it (the snapshot path stays import-light).
    from api.client import Client

    return Client(city).street_crimes_timerange(
        TIMERANGE_START_YEAR,
        TIMERANGE_END_YEAR,
        exclude_year_month=TIMERANGE_EXCLUDE_YEAR_MONTH,
    )


def load_raw_crime(city: str, refresh: bool = False) -> pd.DataFrame:
    """Raw crime rows (RAW_COLUMNS), served from the parquet snapshot when
    available, otherwise fetched and snapshotted."""
    city = city.lower()
    snapshot = crime_snapshot(city)
    if not refresh and snapshot.exists():
        return pd.read_parquet(snapshot)

    raw = _fetch_raw_crime(city)
    try:
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        raw.to_parquet(snapshot, index=False)
    except Exception:  # snapshotting is a cache optimisation, never fatal
        pass
    return raw


def _enrich(raw: pd.DataFrame) -> pd.DataFrame:
    """Merge weights + ward lookup and compute composite columns.

    Reproduces app.py:316-385. NaN severities are coerced to 0 (preventability
    retained); categories absent from the weights CSV get conservative defaults.
    """
    weights = load_weights()
    lsoa_to_ward = pd.read_csv(LSOA_TO_WARD_CSV)

    crime = raw.copy()
    crime["lsoa_code"] = crime["lsoa_code"].astype(str)
    # Collapse slug/typo category variants to the canonical 14 names so they
    # match the weights table and present as one clean list downstream.
    crime["category"] = crime["category"].replace(CANONICAL_CATEGORY)
    lsoa_to_ward["lsoa_code"] = lsoa_to_ward["lsoa_code"].astype(str)
    lsoa_to_ward["ward_code"] = lsoa_to_ward["ward_code"].astype(str)

    crime = crime.merge(weights, on="category", how="left")
    crime = crime.merge(lsoa_to_ward, on="lsoa_code", how="left")

    # A category present in the data but absent from category_weights.csv:
    # conservative defaults so it stays visible in raw/share modes.
    unmapped = crime["preventability_multiplier"].isna()
    if unmapped.any():
        crime.loc[unmapped, "severity_weight_mean"] = 0.0
        crime.loc[unmapped, "severity_weight_median"] = 0.0
        crime.loc[unmapped, "preventability_multiplier"] = 0.0
        crime.loc[unmapped, "preventability_tier"] = "Low"
        crime.loc[unmapped, "preventability_confidence"] = "Low"
        crime.loc[unmapped, "preventability_anchor"] = "(no anchor)"

    # Categories with no CCHI mapping (e.g. Anti-social behaviour) keep their
    # preventability values but have NaN severity -> coerce to 0 for arithmetic.
    crime["severity_weight_mean"] = crime["severity_weight_mean"].fillna(0.0)
    crime["severity_weight_median"] = crime["severity_weight_median"].fillna(0.0)

    crime = add_composite_columns(crime)

    # Low-cardinality columns -> categorical for ~3x faster boolean filtering on
    # the multi-million-row frame (app.py:325-332, 365).
    for col in ("lsoa_code", "borough", "category", "preventability_tier"):
        if col in crime.columns:
            crime[col] = crime[col].astype("category")

    return crime


@lru_cache(maxsize=4)
def get_crime_long(city: str) -> pd.DataFrame:
    """The enriched long crime DataFrame, loaded once and memoised."""
    return _enrich(load_raw_crime(city))


def filter_crime_df(
    df: pd.DataFrame,
    categories: tuple[str, ...] = (),
    tier: str = TIER_ALL,
    year: int | None = None,
    months: tuple[int, ...] = (),
    borough: str = BOROUGH_ALL,
) -> pd.DataFrame:
    """Apply the sidebar filters (app.py:424-439).

    Empty ``categories``/``months`` mean "all". ``tier``/``borough`` accept
    their "All ..." sentinels; ``year`` accepts None or the "All years"
    sentinel.
    """
    out = df
    if categories:
        out = out[out["category"].isin(list(categories))]
    if tier and tier != TIER_ALL:
        out = out[out["preventability_tier"] == tier]
    if year is not None and year != YEAR_ALL:
        out = out[out["year"] == int(year)]
    if months:
        out = out[out["month"].isin(list(months))]
    if borough and borough != BOROUGH_ALL:
        out = out[out["borough"] == borough]
    return out


def aggregate(df: pd.DataFrame, level: str) -> pd.DataFrame:
    """Sum the metric columns to the given level, keyed by its id column.

    Ward aggregation drops rows whose LSOA falls outside any ward polygon
    (app.py:448-459). Returns a frame with the id column + METRIC_COLUMNS.
    """
    level = level.lower()
    if level not in ID_COLUMN_BY_LEVEL:
        raise ValueError(f"unknown level {level!r}")
    id_col = ID_COLUMN_BY_LEVEL[level]

    work = df
    if level == "ward":
        work = work.dropna(subset=["ward_code"])

    aggregated = (
        work.groupby(id_col, as_index=False, observed=True)[list(METRIC_COLUMNS)].sum()
    )
    aggregated[id_col] = aggregated[id_col].astype(str)
    return aggregated
