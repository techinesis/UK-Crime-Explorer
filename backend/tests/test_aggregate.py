"""Unit tests for filtering and aggregation (synthetic fixture, no network)."""

import numpy as np
import pandas as pd

from core.composite import METRIC_COLUMNS, add_composite_columns
from core.data import aggregate, filter_crime_df


def _long_fixture() -> pd.DataFrame:
    """A tiny enriched long frame: 2 LSOAs in 2 boroughs, 2 categories,
    2 wards, across 2 (year, month) periods."""
    rows = [
        # lsoa, borough, category, tier, year, month, ward, count, sevm, sevmed, prev
        ("E01", "Camden", "Burglary", "Medium", 2024, 1, "W1", 10, 100.0, 50.0, 0.5),
        ("E01", "Camden", "Drugs", "High", 2024, 1, "W1", 5, 20.0, 10.0, 1.0),
        ("E02", "Hackney", "Burglary", "Medium", 2024, 2, "W2", 7, 100.0, 50.0, 0.5),
        ("E02", "Hackney", "Drugs", "High", 2025, 1, np.nan, 3, 20.0, 10.0, 1.0),
    ]
    df = pd.DataFrame(
        rows,
        columns=[
            "lsoa_code", "borough", "category", "preventability_tier",
            "year", "month", "ward_code", "crime_count",
            "severity_weight_mean", "severity_weight_median", "preventability_multiplier",
        ],
    )
    return add_composite_columns(df)


def test_filter_empty_categories_means_all():
    df = _long_fixture()
    assert len(filter_crime_df(df)) == len(df)


def test_filter_by_category():
    df = _long_fixture()
    out = filter_crime_df(df, categories=("Drugs",))
    assert set(out["category"]) == {"Drugs"}
    assert len(out) == 2


def test_filter_by_tier_and_year():
    df = _long_fixture()
    out = filter_crime_df(df, tier="High", year=2024)
    assert len(out) == 1
    assert out.iloc[0]["lsoa_code"] == "E01"


def test_filter_by_borough_and_month():
    df = _long_fixture()
    out = filter_crime_df(df, borough="Hackney", months=(2,))
    assert len(out) == 1
    assert out.iloc[0]["category"] == "Burglary"


def test_aggregate_borough_sums_counts():
    df = _long_fixture()
    agg = aggregate(df, "borough")
    assert set(agg["borough"]) == {"Camden", "Hackney"}
    camden = agg.set_index("borough").loc["Camden"]
    assert camden["crime_count"] == 15  # 10 + 5
    # composite_mean: 10*100*0.5 + 5*20*1.0 = 500 + 100 = 600
    assert camden["composite_weighted_mean"] == 600.0
    assert all(col in agg.columns for col in METRIC_COLUMNS)


def test_aggregate_lsoa_row_count():
    df = _long_fixture()
    agg = aggregate(df, "lsoa")
    assert set(agg["lsoa_code"]) == {"E01", "E02"}


def test_aggregate_ward_drops_unmatched():
    df = _long_fixture()
    # One row has NaN ward_code (E02/Drugs/2025) -> dropped from ward aggregation.
    agg = aggregate(df, "ward")
    assert set(agg["ward_code"]) == {"W1", "W2"}
    assert agg.set_index("ward_code").loc["W2", "crime_count"] == 7
