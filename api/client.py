from requests.exceptions import HTTPError
from typing import Optional
from shapely.geometry import Point
import time
from datetime import datetime
from requests import get
from pathlib import Path
import geopandas as gpd
import pandas as pd
import tarfile
from concurrent.futures import ThreadPoolExecutor, as_completed


CRIME_CACHE_PATH = Path(".cache/crime-data")
LSOA_CACHE_PATH = Path(".cache/london_lsoa_boundaries.geojson")

LSOA_DATA_PATH = Path("data/statistical-gis-boundaries-london/ESRI/LSOA_2011_London_gen_MHW.shp")
CRIME_DATA_PATH = Path("data/crime-data.tar.xz")


def __now_year_month() -> tuple[int, int]:
    now = datetime.now()
    return now.year, now.month


def _given_date_or_now(year: int, month: int) -> tuple[int, int]:
    cur_year, cur_month = __now_year_month()
    year = year if year >= 0 else cur_year
    month = month if month > 1 and month <= 12 else cur_month
    return year, month


def make_london_polys(cols: int = 3, rows: int = 3) -> list[dict]:
    W = -0.52
    S = 51.28
    E = 0.35
    N = 51.70

    lon_step = (E - W) / cols
    lat_step = (N - S) / rows

    polys = []

    for r in range(rows):
        for c in range(cols):
            x0 = W + c * lon_step
            x1 = x0 + lon_step
            y0 = S + r * lat_step
            y1 = y0 + lat_step

            poly = f"{y1:.2f},{x0:.2f}:{y1:.2f},{x1:.2f}:{y0:.2f},{x1:.2f}:{y0:.2f},{x0:.2f}"

            polys.append({"bounds": (x0, y0, x1, y1), "poly": poly})

    return polys


def split_poly(poly: str, splits: int = 2) -> list[str]:
    coords = [c.split(",") for c in poly.split(":")]
    lats = [float(c[0]) for c in coords]
    lngs = [float(c[1]) for c in coords]

    min_lat, max_lat = min(lats), max(lats)
    min_lng, max_lng = min(lngs), max(lngs)

    lat_step = (max_lat - min_lat) / splits
    lng_step = (max_lng - min_lng) / splits

    polys = []
    for r in range(splits):
        for c in range(splits):
            s_lat = min_lat + r * lat_step
            n_lat = s_lat + lat_step
            w_lng = min_lng + c * lng_step
            e_lng = w_lng + lng_step
            polys.append(
                f"{n_lat:.2f},{w_lng:.2f}:{n_lat:.2f},{e_lng:.2f}:{s_lat:.2f},{e_lng:.2f}:{s_lat:.2f},{w_lng:.2f}"
            )

    return polys


def prepare_premade_crime_data():
    print("[LOG] Extracting existing crime data")

    CRIME_CACHE_PATH.mkdir(parents=True, exist_ok=True)

    crime_data = tarfile.open(CRIME_DATA_PATH, "r:xz")
    crime_data.extractall(CRIME_CACHE_PATH.parent)


def load_london_lsoas() -> gpd.GeoDataFrame:
    if LSOA_CACHE_PATH.exists():
        return gpd.read_file(LSOA_CACHE_PATH)

    gdf = gpd.read_file(LSOA_DATA_PATH)
    gdf = gdf[["LSOA11CD", "LSOA11NM", "LAD11NM", "geometry"]].rename(
        columns={
            "LSOA11CD": "lsoa_code",
            "LSOA11NM": "lsoa_name",
            "LAD11NM": "borough",
        }
    )
    # Ensure strings
    gdf["lsoa_code"] = gdf["lsoa_code"].astype(str)
    # Convert to WGS84 for web maps
    gdf = gdf.to_crs(epsg=4326)
    # Simplify geometries to make Folium much smoother
    # Increase this slightly if the app is still slow, for example 0.0008
    gdf["geometry"] = gdf["geometry"].simplify(tolerance=0.0005, preserve_topology=True)

    gdf.to_file(LSOA_CACHE_PATH, driver="GeoJSON")

    return gdf


class CrimeCategory:
    def __init__(self, url: str, name: str):
        self.__url = url
        self.__name = name

    def url(self) -> str:
        return self.__url

    def name(self) -> str:
        return self.__name

    def __str__(self) -> str:
        return "{} ({})".format(self.__name, self.__url)


class Client:
    __london_polys = make_london_polys()
    __lsoa_gdf = load_london_lsoas()
    __api_base_url: str = "https://data.police.uk/api/"

    def __init__(self):
        pass

    def __url(self, endpoint: str) -> str:
        return self.__api_base_url + endpoint

    def _enrich_with_lsoa(self, crimes: list[dict]) -> list[dict]:
        if not crimes:
            return []

        records = []
        for c in crimes:
            records.append({
                "_crime": c,
                "geometry": Point(
                    float(c["location"]["longitude"]),
                    float(c["location"]["latitude"]),
                ),
            })

        crimes_gdf = gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:4326")

        joined = gpd.sjoin(
            crimes_gdf,
            self.__lsoa_gdf[["lsoa_code", "lsoa_name", "borough", "geometry"]],
            how="left",
            predicate="within",
        )

        enriched = []
        for _, row in joined.iterrows():
            crime = row["_crime"].copy()

            def _val(field):
                v = row.get(field)
                return None if pd.isna(v) else v

            crime["lsoa_code"] = _val("lsoa_code")
            crime["lsoa_name"] = _val("lsoa_name")
            crime["borough"] = _val("borough")

            enriched.append(crime)

        return enriched

    def crime_categories(self, year: int = -1, month: int = -1) -> list[CrimeCategory]:
        """
        Request available crime categories for a given year and month.
        """
        year, month = _given_date_or_now(year, month)

        r = get(self.__url("crime-categories"), params={"year": year, "month": month})
        r.raise_for_status()

        return [CrimeCategory(c["url"], c["name"]) for c in r.json()]

    def street_crimes_in_poly(
        self, poly: str, category: str, date: str, enriched: bool = True
    ) -> list[dict]:
        params = {"poly": poly, "date": date}

        r = get(
            self.__url(f"crimes-street/{category}"),
            params=params,
            timeout=60,
        )

        if r.status_code == 503:
            results = []
            print("[DBG] Got 503, splitting polygon")
            for sub_poly in split_poly(poly, splits=2):
                try:
                    results.extend(self.street_crimes_in_poly(sub_poly, category, date))
                except HTTPError:
                    pass
                time.sleep(1)
            return results

        r.raise_for_status()
        data = r.json()
        return data if not enriched else self._enrich_with_lsoa(data)

    def street_crimes(self, date: str, category: str = "all-crime") -> pd.DataFrame:
        cache_path = CRIME_CACHE_PATH.joinpath(f"{date}.csv")
        if category == "all-crime" and cache_path.exists():
            return pd.read_csv(cache_path)

        seen_ids: set = set()
        all_crimes: list[dict] = []

        def _add_crime_if_new(c):
            cid = c.get("id") or c.get("persistent_id")
            if cid not in seen_ids:
                seen_ids.add(cid)
                all_crimes.append(c)

        def _fetch_poly(poly, category, date):
            crimes = self.street_crimes_in_poly(poly["poly"], category, date, enriched=False)
            time.sleep(2)
            return crimes

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {
                executor.submit(_fetch_poly, poly, category, date): poly
                for poly in self.__london_polys
            }
            for future in tqdm(as_completed(futures), total=len(futures), desc="Poly"):
                for c in tqdm(future.result(), desc="Crime"):
                    _add_crime_if_new(c)

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame([
            {
                "id": c.get("id"),
                "persistent_id": c.get("persistent_id"),
                "year": int(c.get("month", "").split("-")[0]),
                "month": int(c.get("month", "").split("-")[1]),
                "category": c.get("category"),
                "location_type": c.get("location_type"),
                "location_subtype": c.get("location_subtype"),
                "latitude": c["location"]["latitude"],
                "longitude": c["location"]["longitude"],
                "street_id": c["location"]["street"]["id"],
                "street_name": c["location"]["street"]["name"],
                "context": c.get("context"),
                "outcome_status": (c.get("outcome_status") or {}).get("category"),
                "outcome_date": (c.get("outcome_status") or {}).get("date"),
                "lsoa_code": c.get("lsoa_code"),
                "lsoa_name": c.get("lsoa_name"),
                "borough": c.get("borough"),
            }
            for c in self._enrich_with_lsoa(all_crimes)
        ])

        df_agg = (
            df
            .groupby(["lsoa_code", "lsoa_name", "borough", "category", "year", "month"])
            .size()
            .to_frame("crime_count")
            .reset_index()
        )

        df_agg.to_csv(cache_path, index=False)

        return df_agg

    def street_crimes_timerange(
        self,
        start_year: int,
        end_year: int,
        exclude_years: Optional[list[int]] = None,
        exclude_months: Optional[list[int]] = None,
        exclude_year_month: Optional[list[str]] = None,
        category: str = "all-crime",
    ) -> pd.DataFrame:
        if not CRIME_CACHE_PATH.exists() or not any(CRIME_CACHE_PATH.iterdir()):
            prepare_premade_crime_data()

        assert start_year <= end_year

        exclude_years = exclude_years if exclude_years is not None else []
        exclude_months = exclude_months if exclude_months is not None else []
        exclude_year_month = exclude_year_month if exclude_year_month is not None else []

        dfs = []

        for year in range(start_year, end_year + 1):
            if year in exclude_years:
                continue

            for month in range(12):
                if month in exclude_months:
                    continue

                year_month = f"{year:04}-{month + 1:02}"

                if year_month in exclude_year_month:
                    continue

                try:
                    dfs.append(self.street_crimes(year_month, category))
                except HTTPError:
                    print(f"[ERR] Failed to fetch data for month {year_month}")
                    continue

        return pd.concat(dfs, axis=0, ignore_index=True)
