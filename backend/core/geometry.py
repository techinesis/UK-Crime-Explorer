"""Per-level unit-id index.

Boundary geometry is served as static files (frontend/public/boundaries/*.json,
on the CDN in production) and never touches Python at runtime. The only thing
the API needs from "geometry" is the full list of unit ids per level, used to
0-fill empty units so they still appear (matching app.py's boundary left-join).

That index is pre-baked to data/unit_ids.json by frontend/scripts/prepare-static.mjs,
so this module has no geopandas dependency — keeping the serverless function lean.
"""

from __future__ import annotations

import json
from functools import lru_cache

from core.paths import UNIT_IDS_JSON

LEVELS: tuple[str, ...] = ("lsoa", "ward", "borough")

# The feature-id property the frontend keys on, per level.
ID_PROP_BY_LEVEL: dict[str, str] = {
    "lsoa": "lsoa_code",
    "ward": "ward_code",
    "borough": "borough",
}


def _validate_level(level: str) -> str:
    level = level.lower()
    if level not in LEVELS:
        raise ValueError(f"unknown level {level!r}; expected one of {LEVELS}")
    return level


@lru_cache(maxsize=1)
def _all_unit_ids() -> dict[str, list[str]]:
    with open(UNIT_IDS_JSON, encoding="utf-8") as fh:
        return json.load(fh)


def unit_ids(level: str) -> list[str]:
    """Every unit id at the level (used to 0-fill the values map)."""
    return [str(i) for i in _all_unit_ids()[_validate_level(level)]]
