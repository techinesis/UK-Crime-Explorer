from shapely.geometry import Point
import time
from datetime import datetime
from requests import get
from pathlib import Path
import geopandas as gpd
import pandas as pd
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed


LONDON_FORCES = ["metropolitan", "city-of-london"]
LSOA_CACHE_PATH = Path(".cache/lsoa_london.gpkg")
CRIME_CACHE_PATH = Path(".cache/crime-data")


def __now_year_month() -> tuple[int, int]:
    now = datetime.now()
    return now.year, now.month


def _given_date_or_now(year: int, month: int) -> tuple[int, int]:
    cur_year, cur_month = __now_year_month()
    year = year if year >= 0 else cur_year
    month = month if month > 1 and month <= 12 else cur_month
    return year, month


LSOA_BOUNDARIES_URL = (
    "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/"
    "Lower_layer_Super_Output_Areas_December_2021_Boundaries_EW_BFC_V10/"
    "FeatureServer/0/query"
)

LSOA_LOOKUP_URL = (
    "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/"
    "LSOA21_UTLA23_EW_LU/FeatureServer/0/query"
)


def download_london_lsoas(cache_path: Path = LSOA_CACHE_PATH) -> gpd.GeoDataFrame:
    if cache_path.exists():
        return gpd.read_file(cache_path)

    cache_path.parent.mkdir(parents=True, exist_ok=True)

    resp = get(
        LSOA_LOOKUP_URL,
        params={
            "where": "UTLA23CD LIKE 'E09%'",
            "outFields": "LSOA21CD,LSOA21NM,UTLA23CD,UTLA23NM",
            "f": "json",
            "resultRecordCount": 5000,
        },
        timeout=30,
    )
    resp.raise_for_status()

    lookup = {
        f["attributes"]["LSOA21CD"]: {
            "lsoa_name": f["attributes"]["LSOA21NM"],
            "borough_code": f["attributes"]["UTLA23CD"],
            "borough_name": f["attributes"]["UTLA23NM"],
        }
        for f in resp.json()["features"]
    }

    all_features = []
    offset = 0

    while True:
        resp = get(
            LSOA_BOUNDARIES_URL,
            params={
                "where": "1=1",
                "outFields": "LSOA21CD,LSOA21NM",
                "outSR": "4326",
                "f": "geojson",
                "resultOffset": offset,
                "resultRecordCount": 2000,
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

        features = data.get("features", [])
        london_features = [f for f in features if f["properties"].get("LSOA21CD") in lookup]
        all_features.extend(london_features)

        if not data.get("exceededTransferLimit"):
            break
        offset += 2000
        time.sleep(0.2)

    gdf = gpd.GeoDataFrame.from_features(all_features, crs="EPSG:4326")
    gdf["borough_code"] = gdf["LSOA21CD"].map(lambda c: lookup.get(c, {}).get("borough_code"))
    gdf["borough_name"] = gdf["LSOA21CD"].map(lambda c: lookup.get(c, {}).get("borough_name"))
    gdf = gdf[["LSOA21CD", "LSOA21NM", "borough_code", "borough_name", "geometry"]]

    gdf.to_file(cache_path, driver="GPKG")
    return gdf


def make_london_polys(cols: int = 5, rows: int = 5) -> list[dict]:
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
    __lsoa_gdf = download_london_lsoas()
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
            self.__lsoa_gdf[["LSOA21CD", "LSOA21NM", "borough_code", "borough_name", "geometry"]],
            how="left",
            predicate="within",
        )

        enriched = []
        for _, row in joined.iterrows():
            crime = row["_crime"].copy()

            def _val(field):
                v = row.get(field)
                return None if pd.isna(v) else v

            crime["lsoa_code"] = _val("LSOA21CD")
            crime["lsoa_name"] = _val("LSOA21NM")
            crime["borough_code"] = _val("borough_code")
            crime["borough_name"] = _val("borough_name")

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

    def street_crimes_in_poly(self, poly: str, category: str, date: str) -> list[dict]:
        params = {"poly": poly, "date": date}

        r = get(
            self.__url(f"crimes-street/{category}"),
            params=params,
            timeout=60,
        )

        if r.status_code == 503:
            results = []
            for sub_poly in split_poly(poly, splits=2):
                results.extend(self.street_crimes_in_poly(sub_poly, category, date))
                time.sleep(1)
            return results

        r.raise_for_status()
        return self._enrich_with_lsoa(r.json())

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
                all_crimes.append({
                    "id": c.get("id"),
                    "persistent_id": c.get("persistent_id"),
                    "month": c.get("month"),
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
                    "borough_code": c.get("borough_code"),
                    "borough_name": c.get("borough_name"),
                })

        def _fetch_poly(poly, category, date):
            crimes = self.street_crimes_in_poly(poly["poly"], category, date)
            time.sleep(2)
            return crimes

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(_fetch_poly, poly, category, date): poly
                for poly in self.__london_polys
            }
            for future in tqdm(as_completed(futures), total=len(futures), desc="Poly"):
                for c in tqdm(future.result(), desc="Crime"):
                    _add_crime_if_new(c)

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame(all_crimes)
        df.to_csv(cache_path, index=False, header=True)

        return df
