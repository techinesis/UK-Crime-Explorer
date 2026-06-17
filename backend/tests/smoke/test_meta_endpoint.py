"""Smoke test 1: GET /api/meta returns the dashboard's bootstrap metadata.

A green check here means the data snapshot loaded and the meta builder still
produces the 14-category list, the borough roster, and the period index the
frontend depends on at startup.
"""

from __future__ import annotations

import pytest


@pytest.mark.smoke
def test_meta_endpoint(meta):
    # The four keys the SPA reads on mount.
    for key in ("years", "months", "categories", "boroughs"):
        assert key in meta, f"/api/meta missing {key!r}"

    # Exactly the 14 canonical categories, each with populated preventability meta.
    categories = meta["categories"]
    assert len(categories) == 14, f"expected 14 categories, got {len(categories)}"
    for cat in categories:
        for field in (
            "name",
            "preventability_tier",
            "preventability_confidence",
            "preventability_anchor",
        ):
            assert cat.get(field), f"category {cat.get('name')!r} missing {field!r}"

    # Borough roster: non-empty and includes two known central-London sanity checks.
    boroughs = meta["boroughs"]
    assert boroughs, "boroughs list is empty"
    assert {"Westminster", "Camden"} <= set(boroughs)

    # At least two years of monthly periods present (each is a [year, month] pair).
    periods = meta["periods"]
    assert len(periods) >= 24, f"expected >=24 periods, got {len(periods)}"
