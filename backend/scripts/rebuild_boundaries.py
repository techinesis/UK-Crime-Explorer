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
import re

from core.paths import DATA_DIR, LSOA_BOUNDARIES, BOROUGH_BOUNDARIES, WARD_BOUNDARIES, LSOA_TO_WARD_CSV

LSOA_SOURCE = DATA_DIR / "lsoa-data" / "LSOA_2021_EW_BSC_V4.shp"
BOROUGH_SOURCE = DATA_DIR / "borough-data" / "LAD_MAY_2025_UK_BFE_V2.shp"
WARD_SOURCE = DATA_DIR / "ward-data" / "WD_MAY_2025_UK_BFC_V2.shp"


def authority_from_lsoa_name(name):
    return re.sub(r"\s+\d+[A-Z]$", "", name)


def build_lsoa() -> gpd.GeoDataFrame:
    gdf = gpd.read_file(LSOA_SOURCE)
    gdf = gdf[["LSOA21CD", "LSOA21NM", "geometry"]].rename(
        columns={"LSOA21CD": "lsoa_code", "LSOA21NM": "lsoa_name"}
    )
    gdf["borough"] = gdf["lsoa_name"].apply(authority_from_lsoa_name)
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
    return gdf


def build_borough() -> gpd.GeoDataFrame:
    gdf = gpd.read_file(BOROUGH_SOURCE)
    gdf = gdf[["LAD25NM", "geometry"]].rename(
        columns={"LAD25NM": "borough"}
    )
    gdf = gdf.to_crs(epsg=4326)
    gdf["geometry"] = gdf["geometry"].simplify(tolerance=0.0005, preserve_topology=True)

    invalid = ~gdf.geometry.is_valid
    if invalid.any():
        gdf.loc[invalid, "geometry"] = gdf.loc[invalid, "geometry"].make_valid()

    BOROUGH_BOUNDARIES.unlink(missing_ok=True)
    gdf.to_file(BOROUGH_BOUNDARIES, driver="GeoJSON")
    print(
        f"wrote {BOROUGH_BOUNDARIES.name}: {len(gdf)} features, "
        f"valid={int(gdf.geometry.is_valid.sum())}/{len(gdf)}"
    )
    return gdf


def build_lsoa_to_ward(lsoa_gdf):
    ward_gdf = gpd.read_file(WARD_SOURCE)
    ward_gdf = ward_gdf[["WD25CD", "WD25NM", "LAD25NM", "geometry"]].rename(
        columns={
            "WD25CD": "ward_code",
            "WD25NM": "ward_name",
            "LAD25NM": "borough",
        }
    )

    ward_gdf = ward_gdf.to_crs(epsg=4326)

    invalid = ~ward_gdf.geometry.is_valid
    if invalid.any():
        ward_gdf.loc[invalid, "geometry"] = ward_gdf.loc[invalid, "geometry"].make_valid()

    WARD_BOUNDARIES.unlink(missing_ok=True)

    lsoa_bng = lsoa_gdf.to_crs(epsg=27700)
    ward_bng = ward_gdf.to_crs(epsg=27700)

    lsoa_centroids = gpd.GeoDataFrame(
        {"lsoa_code": lsoa_bng["lsoa_code"]},
        geometry=lsoa_bng.geometry.centroid,
        crs=lsoa_bng.crs
    )

    lsoa_to_ward = gpd.sjoin(
        lsoa_centroids,
        ward_bng[["ward_code", "geometry"]],
        how="left",
        predicate="within",
    )[["lsoa_code", "ward_code"]]

    unmatched = int(lsoa_to_ward["ward_code"].isna().sum())
    if unmatched:
        print(f"warning {unmatched} LSOAs did not match any ward")

    lsoa_to_ward.to_csv(LSOA_TO_WARD_CSV, index=False)

    ward_gdf["geometry"] = ward_gdf["geometry"].simplify(tolerance=0.0005, preserve_topology=True)
    ward_gdf.to_file(WARD_BOUNDARIES, driver="GeoJSON")
    print(
        f"wrote {WARD_BOUNDARIES.name}: {len(ward_gdf)} features, "
        f"valid={int(ward_gdf.geometry.is_valid.sum())}/{len(ward_gdf)}"
    )

    


if __name__ == "__main__":
    lsoa_gdf = build_lsoa()
    borough_gdf = build_borough()

    build_lsoa_to_ward(lsoa_gdf)
