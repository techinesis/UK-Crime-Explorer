"""Smoke test 2: POST /api/map across every metric and level.

Drives the five map modes at all three aggregation levels with a fixed filter.
Guards the mode->column resolution, the 0-fill that keeps every unit present, and
the vmin/vmax colour-scale invariants the frontend relies on.

One function with an internal loop (not parametrize) so the suite collects exactly
seven smoke items; the failing metric/level is named in each assert message.
"""

from __future__ import annotations

import pytest

from core import geometry

METRICS = ("raw", "share", "severity", "preventability", "composite")
LEVELS = ("lsoa", "ward", "borough")


@pytest.mark.smoke
def test_map_endpoints(client, sample_filter):
    for level in LEVELS:
        expected_ids = set(geometry.unit_ids(level))
        for metric in METRICS:
            payload = {**sample_filter, "metric": metric, "level": level}
            res = client.post("/api/map", json=payload)
            where = f"metric={metric} level={level}"
            assert res.status_code == 200, f"{where}: {res.text}"
            body = res.json()

            # Every unit at the level is present (0-filled), matching unit_ids.json.
            assert set(body["values"]) == expected_ids, f"{where}: unit id set mismatch"

            vmin, vmax = body["vmin"], body["vmax"]
            assert vmin >= 0, f"{where}: vmin {vmin} < 0"
            assert vmax >= vmin, f"{where}: vmax {vmax} < vmin {vmin}"
            if metric == "share":
                # share is a 0-100 percentage with vmax floored to 1.0.
                assert 1.0 <= vmax <= 100.0, f"{where}: share vmax {vmax} outside [1, 100]"
