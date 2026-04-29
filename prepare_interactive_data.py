import os
import pandas as pd
import geopandas as gpd

os.makedirs("outputs", exist_ok=True)

crime_path = "data/london_crime_by_lsoa.csv"
boundary_path = "data/statistical-gis-boundaries-london/ESRI/LSOA_2011_London_gen_MHW.shp"

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

print("Done.")
print("Created:")
print("- outputs/london_lsoa_boundaries_clean.geojson")
print("- outputs/crime_aggregated_for_app.csv")