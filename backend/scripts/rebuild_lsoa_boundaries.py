"""Regenerate the LSOA display geometry from the source shapefile.

The previous clean GeoJSON was built with per-feature ``simplify(0.0005)``, which
breaks topology between adjacent LSOAs (their shared edges no longer coincide),
showing as sliver gaps when zoomed in. deck.gl renders the full generalised
geometry on the GPU without trouble, so we keep the source vertices — adjacent
LSOAs then share identical vertices and borders align exactly.

Run from backend/:  PYTHONPATH=. python scripts/rebuild_lsoa_boundaries.py
"""

from __future__ import annotations

import geopandas as gpd

from core.paths import DATA_DIR, LSOA_BOUNDARIES

SOURCE = DATA_DIR / "statistical-gis-boundaries-london" / "ESRI" / "LSOA_2011_London_gen_MHW.shp"


def main() -> None:
    gdf = (
        gpd.read_file(SOURCE)[["LSOA11CD", "LSOA11NM", "LAD11NM", "geometry"]]
        .rename(columns={"LSOA11CD": "lsoa_code", "LSOA11NM": "lsoa_name", "LAD11NM": "borough"})
    )
    gdf["lsoa_code"] = gdf["lsoa_code"].astype(str)
    gdf = gdf.to_crs(epsg=4326)

    invalid = ~gdf.geometry.is_valid
    if invalid.any():
        gdf.loc[invalid, "geometry"] = gdf.loc[invalid, "geometry"].make_valid()

    # No simplification — preserves shared topology so borders align.
    LSOA_BOUNDARIES.unlink(missing_ok=True)
    gdf.to_file(LSOA_BOUNDARIES, driver="GeoJSON")
    print(
        f"wrote {LSOA_BOUNDARIES.name}: {len(gdf)} features, "
        f"valid={int(gdf.geometry.is_valid.sum())}/{len(gdf)}"
    )


if __name__ == "__main__":
    main()
