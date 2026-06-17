"""Smoke test: the chat's get_forecast tool reads the committed forecast end-to-end.

No LLM, no network — it drives the registered tool via ``dispatch_tool`` against the
committed forecast file, proving the chat actually sees the forecast pipeline the
dashboard renders.
"""

from __future__ import annotations

import pytest

from core.chat import dispatch_tool


@pytest.mark.smoke
def test_get_forecast_tool_returns_ranked_borough_forecast():
    result, action, summary = dispatch_tool(
        "get_forecast", {"city": "london", "group_by": "borough", "top_n": 5}
    )
    assert action is None
    assert "error" not in result
    assert set(result) == {"rows", "filters", "total_predicted", "n_rows_after_filter"}
    assert result["n_rows_after_filter"] > 0
    assert result["total_predicted"] > 0
    rows = result["rows"]
    assert 1 <= len(rows) <= 5
    values = [r["predicted_crimes"] for r in rows]
    assert values == sorted(values, reverse=True)  # ranked descending
