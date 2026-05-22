"""FastAPI integration tests against the real (snapshotted) data.

These exercise the loaded crime frame, so they are slower than the pure unit
tests. They confirm the HTTP layer matches the core functions exactly.
"""

import pytest
from fastapi.testclient import TestClient

from api.main import app
from core.data import aggregate, filter_crime_df, get_crime_long


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # triggers lifespan startup load
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_meta_shape(client):
    r = client.get("/api/meta")
    assert r.status_code == 200
    body = r.json()
    assert 2024 in body["years"]
    assert set(body["months"]).issubset(set(range(1, 13)))
    assert body["tiers"] == ["All tiers", "High", "Medium", "Low"]
    assert len(body["categories"]) > 0
    # every category carries the four metadata fields
    cat = body["categories"][0]
    assert set(cat) == {
        "name", "preventability_tier", "preventability_confidence", "preventability_anchor"
    }
    assert len(body["boroughs"]) == 33


def test_weights(client):
    r = client.get("/api/weights")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 14
    assert "preventability_anchor" in rows[0]


def test_map_borough_raw_matches_core(client):
    """Hand-check: /api/map borough/raw values equal the core aggregation."""
    df = get_crime_long()
    agg = aggregate(filter_crime_df(df), "borough")
    expected = dict(zip(agg["borough"].astype(str), agg["crime_count"].astype(float)))

    r = client.post("/api/map", json={"level": "borough", "metric": "raw"})
    assert r.status_code == 200
    body = r.json()
    assert len(body["values"]) == 33  # every borough present (0-filled)
    for borough, count in expected.items():
        assert body["values"][borough] == count
        assert body["crime_counts"][borough] == count
    assert body["vmax"] >= 1.0


def test_map_share_sums_to_100(client):
    r = client.post("/api/map", json={"level": "borough", "metric": "share"})
    body = r.json()
    assert pytest.approx(sum(body["values"].values()), rel=1e-6) == 100.0


def test_map_lsoa_returns_all_units(client):
    r = client.post("/api/map", json={"level": "lsoa", "metric": "composite"})
    assert len(r.json()["values"]) == 4835


def test_map_severity_basis_changes_values(client):
    base = {"level": "borough", "metric": "severity"}
    mean = client.post("/api/map", json={**base, "severity_basis": "mean"}).json()
    median = client.post("/api/map", json={**base, "severity_basis": "median"}).json()
    assert mean["values"] != median["values"]
