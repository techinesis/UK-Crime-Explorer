"""Smoke test 4: the four chat tools dispatch correctly against real data.

Calls core.chat.dispatch_tool directly (the pattern from test_forecast.py /
test_allocation.py). The query_data case is cross-checked against POST /api/map
to prove the tool layer reads the same data path as the route.
"""

from __future__ import annotations

import pytest

from core.chat import dispatch_tool

# Drugs in Camden, March 2024 — a concrete, data-bearing selection (46 LSOA rows).
_FILTER = {"categories": ["Drugs"], "borough": "Camden", "year": 2024, "months": [3]}


@pytest.mark.smoke
def test_chat_tools(client):
    # --- set_filters: returns a filter-delta action mirroring the input ---------
    result, action, summary = dispatch_tool("set_filters", dict(_FILTER))
    assert action is not None, "set_filters returned no action"
    assert action["type"] == "set_filters"
    payload = action["payload"]
    assert payload["categories"] == ["Drugs"]
    assert payload["borough"] == "Camden"
    assert payload["year"] == 2024
    assert payload["months"] == [3]

    # --- query_data: documented aggregation shape + cross-check vs /api/map ------
    query_filter = {**_FILTER, "level": "lsoa", "metric": "raw"}
    result, action, summary = dispatch_tool("query_data", dict(query_filter))
    assert action is None, "query_data should not emit an action"
    expected_keys = {
        "metric",
        "level",
        "group_by",
        "severity_basis",
        "filters_applied",
        "unit_count",
        "total_crime_count",
        "vmin",
        "vmax",
        "top",
    }
    assert expected_keys <= set(result), f"query_data missing keys: {expected_keys - set(result)}"
    top = result["top"]
    assert top, "query_data returned no ranked rows"
    values = [row["value"] for row in top]
    assert values == sorted(values, reverse=True), "query_data top not ranked descending"
    for row in top:
        assert {"id", "name", "value", "crime_count"} <= set(row)

    # The top-ranked unit must be the argmax of /api/map for the same filter — the
    # tool and the route must read the same data path, not a divergent one.
    map_res = client.post(
        "/api/map",
        json={**query_filter, "tier": "All tiers", "severity_basis": "mean", "city": "london"},
    )
    assert map_res.status_code == 200, map_res.text
    map_values = map_res.json()["values"]
    top_id = top[0]["id"]
    assert map_values[top_id] == pytest.approx(max(map_values.values())), (
        "query_data top unit is not the /api/map maximum"
    )
    assert map_values[top_id] == pytest.approx(top[0]["value"], abs=0.5), (
        "query_data top value disagrees with /api/map"
    )

    # --- get_weights: 14 rows, each with the seven documented columns -----------
    result, action, summary = dispatch_tool("get_weights", {})
    assert action is None
    weight_rows = result["categories"]
    assert len(weight_rows) == 14, f"expected 14 weight rows, got {len(weight_rows)}"
    expected_cols = {
        "category",
        "severity_weight_mean",
        "severity_weight_median",
        "preventability_multiplier",
        "preventability_tier",
        "preventability_confidence",
        "preventability_anchor",
    }
    for row in weight_rows:
        assert expected_cols <= set(row), f"weights row missing cols: {expected_cols - set(row)}"

    # --- read_docs: the BM25 corpus is built over the right source files --------
    result, action, summary = dispatch_tool("read_docs", {"topic": "preventability"})
    assert action is None
    chunks = result["chunks"]
    assert chunks, "read_docs returned no chunks for 'preventability'"
    assert any("prepare_category_weights.py" in chunk["source"] for chunk in chunks), (
        "read_docs did not surface prepare_category_weights.py for 'preventability'"
    )
