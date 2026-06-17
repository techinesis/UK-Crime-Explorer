"""Smoke test (Phase 2): GET /api/health returns 200.

The app's liveness probe. Cheap, but a non-200 here means the FastAPI app failed
to import or boot at all — the fastest possible signal that something is broken
before any feature-level test even runs.
"""

from __future__ import annotations

import pytest


@pytest.mark.smoke
def test_api_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
