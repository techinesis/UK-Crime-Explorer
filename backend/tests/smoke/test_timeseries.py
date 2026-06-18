"""Smoke test (Phase 3 polish): GET /api/timeseries.

Exercises the per-LSOA monthly time-series endpoint that backs the recap-panel
sparkline. Runs against the committed real data via the shared `client` fixture
— no network, no LLM. A regression here means a broken sparkline on the
dashboard.
"""

from __future__ import annotations

import pytest

from core.data import get_crime_long


def _real_lsoa_and_category() -> tuple[str, str]:
    """A (lsoa_code, category) pair taken from the same real row, so the LSOA is
    guaranteed to exist in the crime data and to have at least one record in
    that category."""
    df = get_crime_long("london")
    first = df.iloc[0]
    return str(first["lsoa_code"]), str(first["category"])


@pytest.mark.smoke
def test_timeseries_known_lsoa(client):
    lsoa_code, _ = _real_lsoa_and_category()

    res = client.get("/api/timeseries", params={"lsoa_code": lsoa_code})
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["lsoa_code"] == lsoa_code
    assert body["lsoa_name"]
    assert body["borough"]

    series = body["series"]
    assert len(series) == 24  # default `months` window

    periods = [(p["year"], p["month"]) for p in series]
    assert periods == sorted(periods)  # ascending by (year, month)
    assert all(p["count"] >= 0 for p in series)  # non-negative, zero-filled gaps


@pytest.mark.smoke
def test_timeseries_unknown_lsoa_404(client):
    res = client.get("/api/timeseries", params={"lsoa_code": "E99999999"})
    assert res.status_code == 404
    assert res.json()["detail"]  # a clear, non-empty error message


@pytest.mark.smoke
def test_timeseries_category_filter(client):
    lsoa_code, category = _real_lsoa_and_category()

    all_cats = client.get("/api/timeseries", params={"lsoa_code": lsoa_code}).json()
    one_cat = client.get(
        "/api/timeseries",
        params={"lsoa_code": lsoa_code, "categories": [category]},
    ).json()

    assert one_cat["categories"] == [category]

    # Same month window for both requests…
    all_periods = [(p["year"], p["month"]) for p in all_cats["series"]]
    one_periods = [(p["year"], p["month"]) for p in one_cat["series"]]
    assert all_periods == one_periods

    # …and filtering to a single category can only reduce each month's count.
    for total, filtered in zip(all_cats["series"], one_cat["series"]):
        assert filtered["count"] <= total["count"]
