"""Filesystem path resolution for the backend.

The data and cache directories live at the repository root (shared with the
legacy Streamlit app during the rewrite). They are resolved relative to this
file so imports work regardless of the process working directory, with
environment-variable overrides for deployment flexibility.
"""

from __future__ import annotations

import os
from pathlib import Path

# backend/core/paths.py -> parents[0]=core, [1]=backend, [2]=repo root
REPO_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = Path(os.environ.get("CRIME_DATA_DIR", REPO_ROOT / "data"))
CACHE_DIR = Path(os.environ.get("CRIME_CACHE_DIR", REPO_ROOT / ".cache"))

# Committed artifacts under data/ (read by the API at runtime — all small, no
# geopandas needed). Boundary GeoJSON is served as static CDN assets, not here.
WEIGHTS_CSV = DATA_DIR / "category_weights.csv"
LSOA_TO_WARD_CSV = DATA_DIR / "lsoa_to_ward.csv"
UNIT_IDS_JSON = DATA_DIR / "unit_ids.json"

# Committed snapshot of the long crime DataFrame — the production data source
# (the 890 MB raw CSV is gitignored; the API never re-fetches when this exists).
CRIME_SNAPSHOT = DATA_DIR / "crime_snapshot.parquet"

# Source boundary GeoJSON, used only by ETL / pre-bake tooling (not the API).
LSOA_BOUNDARIES = DATA_DIR / "london_lsoa_boundaries_clean.geojson"
BOROUGH_BOUNDARIES = DATA_DIR / "london_borough_boundaries_clean.geojson"
WARD_BOUNDARIES = DATA_DIR / "london_ward_boundaries_clean.geojson"
BOUNDARY_FILE_BY_LEVEL = {
    "lsoa": LSOA_BOUNDARIES,
    "ward": WARD_BOUNDARIES,
    "borough": BOROUGH_BOUNDARIES,
}
