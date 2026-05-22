"""Boundary GeoJSON loading and trimming.

Boundaries are large and static, so they are loaded and serialised once per
level (lru_cache) and served whole; only the small per-filter values map
changes per request. Geometries are pre-``explode()``-ed (MultiPolygon ->
Polygon rows) for the same reason app.py does it: deck.gl's GeoJsonLayer is
more reliable with single-Polygon features.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache

import geopandas as gpd

from core.paths import BOUNDARY_FILE_BY_LEVEL

LEVELS: tuple[str, ...] = ("lsoa", "ward", "borough")

# The feature-id property the frontend keys on, per level.
ID_PROP_BY_LEVEL: dict[str, str] = {
    "lsoa": "lsoa_code",
    "ward": "ward_code",
    "borough": "borough",
}

# Properties kept on served features (id + tooltip fields). Everything else is
# dropped to keep the payload small.
_KEEP_PROPS_BY_LEVEL: dict[str, list[str]] = {
    "lsoa": ["lsoa_code", "lsoa_name", "borough"],
    "ward": ["ward_code", "ward_name", "borough"],
    "borough": ["borough"],
}


def _validate_level(level: str) -> str:
    level = level.lower()
    if level not in LEVELS:
        raise ValueError(f"unknown level {level!r}; expected one of {LEVELS}")
    return level


@lru_cache(maxsize=len(LEVELS))
def _load_boundary(level: str) -> gpd.GeoDataFrame:
    level = _validate_level(level)
    gdf = gpd.read_file(BOUNDARY_FILE_BY_LEVEL[level])
    gdf = gdf.explode(index_parts=False, ignore_index=True)
    id_col = ID_PROP_BY_LEVEL[level]
    gdf[id_col] = gdf[id_col].astype(str)
    keep = [c for c in _KEEP_PROPS_BY_LEVEL[level] if c in gdf.columns]
    return gdf[[*keep, "geometry"]]


@lru_cache(maxsize=len(LEVELS))
def get_boundaries_json(level: str) -> str:
    """Return a trimmed GeoJSON FeatureCollection string for the level."""
    return _load_boundary(_validate_level(level)).to_json()


@lru_cache(maxsize=len(LEVELS))
def get_boundaries_etag(level: str) -> str:
    """Content-based ETag so the browser revalidates when geometry changes."""
    digest = hashlib.md5(get_boundaries_json(_validate_level(level)).encode()).hexdigest()
    return f'"{digest}"'


def unit_ids(level: str) -> list[str]:
    """Every unit id at the level (used to 0-fill the values map)."""
    level = _validate_level(level)
    return _load_boundary(level)[ID_PROP_BY_LEVEL[level]].drop_duplicates().tolist()
