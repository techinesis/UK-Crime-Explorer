"""Unit tests for the composite math and metric resolution (no I/O)."""

import math

import pandas as pd
import pytest

from core.composite import (
    METRIC_COLUMNS,
    VALID_METRICS,
    add_composite_columns,
    compute_map_values,
    resolve_metric,
)


def _fixture() -> pd.DataFrame:
    # Two units; second has a NaN-coerced (0) severity like Anti-social behaviour.
    return pd.DataFrame(
        {
            "id": ["A", "B"],
            "crime_count": [10, 4],
            "severity_weight_mean": [8.0, 0.0],
            "severity_weight_median": [3.0, 0.0],
            "preventability_multiplier": [0.5, 1.0],
        }
    )


def test_add_composite_columns_formulas():
    out = add_composite_columns(_fixture())
    # Row A: crime_count=10, sev_mean=8, sev_median=3, prevent=0.5
    assert out.loc[0, "severity_weighted_mean"] == 80.0
    assert out.loc[0, "severity_weighted_median"] == 30.0
    assert out.loc[0, "preventability_weighted"] == 5.0
    assert out.loc[0, "composite_weighted_mean"] == 40.0   # 10 * 8 * 0.5
    assert out.loc[0, "composite_weighted_median"] == 15.0  # 10 * 3 * 0.5
    # Row B: zero severity -> zero severity/composite, preventability survives
    assert out.loc[1, "severity_weighted_mean"] == 0.0
    assert out.loc[1, "composite_weighted_mean"] == 0.0
    assert out.loc[1, "preventability_weighted"] == 4.0  # 4 * 1.0


def test_add_composite_columns_is_pure():
    df = _fixture()
    before = df.copy()
    add_composite_columns(df)
    pd.testing.assert_frame_equal(df, before)  # input untouched


@pytest.mark.parametrize(
    "metric,basis,expected",
    [
        ("raw", "mean", "crime_count"),
        ("share", "mean", "crime_count"),
        ("severity", "mean", "severity_weighted_mean"),
        ("severity", "median", "severity_weighted_median"),
        ("preventability", "median", "preventability_weighted"),
        ("composite", "mean", "composite_weighted_mean"),
        ("composite", "median", "composite_weighted_median"),
    ],
)
def test_resolve_metric(metric, basis, expected):
    assert resolve_metric(metric, basis) == expected
    assert expected in METRIC_COLUMNS


def test_resolve_metric_rejects_bad_input():
    with pytest.raises(ValueError):
        resolve_metric("bogus", "mean")
    with pytest.raises(ValueError):
        resolve_metric("raw", "bogus")


def test_compute_map_values_raw():
    agg = add_composite_columns(_fixture())
    values, vmin, vmax = compute_map_values(agg, "raw", "mean")
    assert list(values) == [10.0, 4.0]
    assert vmin == 4.0
    assert vmax == 10.0


def test_compute_map_values_share_is_percentage_of_total():
    agg = add_composite_columns(_fixture())  # crime_count 10 + 4 = 14
    values, vmin, vmax = compute_map_values(agg, "share", "mean")
    assert math.isclose(values.iloc[0], 10 / 14 * 100)
    assert math.isclose(values.iloc[1], 4 / 14 * 100)
    assert math.isclose(values.sum(), 100.0)


def test_compute_map_values_vmax_floored_to_one():
    # All-zero metric -> vmax must floor to 1.0 for a valid colour normalisation.
    agg = add_composite_columns(
        pd.DataFrame(
            {
                "id": ["A"],
                "crime_count": [0],
                "severity_weight_mean": [0.0],
                "severity_weight_median": [0.0],
                "preventability_multiplier": [0.0],
            }
        )
    )
    _, vmin, vmax = compute_map_values(agg, "composite", "mean")
    assert vmin == 0.0
    assert vmax == 1.0


def test_all_modes_have_a_resolution():
    for metric in VALID_METRICS:
        assert resolve_metric(metric, "mean") in METRIC_COLUMNS
