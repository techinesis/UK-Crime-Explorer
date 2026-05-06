import os
import pandas as pd
import geopandas as gpd

os.makedirs("outputs", exist_ok=True)

crime_path = "data/london_crime_by_lsoa.csv"
boundary_path = "data/statistical-gis-boundaries-london/ESRI/LSOA_2011_London_gen_MHW.shp"
borough_boundary_path = "data/statistical-gis-boundaries-london/ESRI/London_Borough_Excluding_MHW.shp"
ward_boundary_path = "data/statistical-gis-boundaries-london/ESRI/London_Ward_CityMerged.shp"

print("Loading crime data...")
crime_df = pd.read_csv(crime_path)

print("Loading LSOA boundary data...")
lsoa_map = gpd.read_file(boundary_path)

# Keep only useful boundary columns
lsoa_map = lsoa_map[
    ["LSOA11CD", "LSOA11NM", "LAD11NM", "geometry"]
].copy()

# Rename columns
lsoa_map = lsoa_map.rename(
    columns={
        "LSOA11CD": "lsoa_code",
        "LSOA11NM": "lsoa_name",
        "LAD11NM": "borough"
    }
)

# Ensure strings
crime_df["lsoa_code"] = crime_df["lsoa_code"].astype(str)
lsoa_map["lsoa_code"] = lsoa_map["lsoa_code"].astype(str)

# Convert to WGS84 for web maps
lsoa_map = lsoa_map.to_crs(epsg=4326)

# Simplify geometries to make Folium much smoother
# Increase this slightly if the app is still slow, for example 0.0008
lsoa_map["geometry"] = lsoa_map["geometry"].simplify(
    tolerance=0.0005,
    preserve_topology=True
)

# Save clean boundaries
lsoa_map.to_file(
    "outputs/london_lsoa_boundaries_clean.geojson",
    driver="GeoJSON"
)

print("Loading borough boundary data...")
borough_map = gpd.read_file(borough_boundary_path)

borough_map = borough_map[["GSS_CODE", "NAME", "geometry"]].copy()

borough_map = borough_map.rename(
    columns={
        "GSS_CODE": "borough_code",
        "NAME": "borough"
    }
)

borough_map = borough_map.to_crs(epsg=4326)

borough_map["geometry"] = borough_map["geometry"].simplify(
    tolerance=0.0005,
    preserve_topology=True
)

borough_map.to_file(
    "outputs/london_borough_boundaries_clean.geojson",
    driver="GeoJSON"
)

print("Loading ward boundary data...")
ward_map = gpd.read_file(ward_boundary_path)

ward_map = ward_map[
    ["GSS_CODE", "NAME", "LB_GSS_CD", "BOROUGH", "geometry"]
].copy()

ward_map = ward_map.rename(
    columns={
        "GSS_CODE": "ward_code",
        "NAME": "ward_name",
        "LB_GSS_CD": "borough_code",
        "BOROUGH": "borough",
    }
)

ward_map = ward_map.to_crs(epsg=4326)

# LSOA → ward lookup via centroid-in-polygon spatial join.
# LSOAs nest inside wards by census design, so a centroid containment check
# produces a clean 1:1 mapping. We compute centroids in British National Grid
# (EPSG:27700) instead of WGS84 because lat/lon centroids are geometrically
# distorted at non-equatorial latitudes; for London the bias is small but
# geopandas correctly warns about it.
print("Building LSOA -> ward lookup...")
lsoa_bng = lsoa_map.to_crs(epsg=27700)
ward_bng = ward_map.to_crs(epsg=27700)

lsoa_centroids = gpd.GeoDataFrame(
    {"lsoa_code": lsoa_bng["lsoa_code"]},
    geometry=lsoa_bng.geometry.centroid,
    crs=lsoa_bng.crs,
)

lsoa_to_ward = gpd.sjoin(
    lsoa_centroids,
    ward_bng[["ward_code", "geometry"]],
    how="left",
    predicate="within",
)[["lsoa_code", "ward_code"]]

unmatched = int(lsoa_to_ward["ward_code"].isna().sum())
if unmatched:
    print(f"  warning: {unmatched} LSOAs did not match any ward")

lsoa_to_ward.to_csv("outputs/lsoa_to_ward.csv", index=False)

ward_map["geometry"] = ward_map["geometry"].simplify(
    tolerance=0.0005,
    preserve_topology=True
)

ward_map.to_file(
    "outputs/london_ward_boundaries_clean.geojson",
    driver="GeoJSON"
)

# Clean crime data
crime_df["value"] = pd.to_numeric(crime_df["value"], errors="coerce").fillna(0)
crime_df["year"] = pd.to_numeric(crime_df["year"], errors="coerce").astype(int)
crime_df["month"] = pd.to_numeric(crime_df["month"], errors="coerce").astype(int)

# Aggregate by LSOA, borough, crime type, year, month
crime_agg = (
    crime_df
    .groupby(
        ["lsoa_code", "borough", "major_category", "year", "month"],
        as_index=False
    )["value"]
    .sum()
    .rename(columns={"value": "crime_count"})
)

crime_agg.to_csv("outputs/crime_aggregated_for_app.csv", index=False)

print("ok")

