"""Smoke test: the chat's get_allocation tool runs the allocation pipeline end-to-end.

Uses ``model="averaging"`` (cheap, always feasible) so the smoke suite stays well
under the 30s budget — the LP/Rawls solvers are exercised by the unit tests in
``test_chat.py``. No LLM, no network.
"""

from __future__ import annotations

import pytest

from core.chat import dispatch_tool


@pytest.mark.smoke
def test_get_allocation_tool_ranks_boroughs():
    result, action, summary = dispatch_tool(
        "get_allocation",
        {"city": "london", "model": "averaging", "group_by": "borough", "top_n": 5},
    )
    assert action is None
    assert "error" not in result
    assert set(result) == {"rows", "model", "total_units", "infeasible_warning"}
    assert result["model"] == "averaging"
    assert result["infeasible_warning"] is None
    rows = result["rows"]
    assert 1 <= len(rows) <= 5
    units = [r["units"] for r in rows]
    assert units == sorted(units, reverse=True)  # ranked descending
