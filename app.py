import hashlib
import json
import time
from pathlib import Path

import pandas as pd
import geopandas as gpd
import numpy as np
import streamlit as st
import folium
from streamlit_folium import st_folium
import branca.colormap as cm
import pydeck as pdk
from matplotlib import colormaps
from matplotlib.colors import Normalize
from api.client import Client


st.set_page_config(
    page_title="London Crime Explorer",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)


# -----------------------------
# Custom CSS
# -----------------------------

st.markdown(
    """
    <style>
        /* Dark-mode-first palette. .streamlit/config.toml pins the theme to
           dark; these rules harden the design so body text stays readable
           even if the config is bypassed (embedded iframe, Streamlit Cloud
           override, etc.). All values are from Tailwind's slate scale. */
        .stApp,
        [data-testid="stAppViewContainer"] {
            background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%);
            color: #f1f5f9;
        }

        /* Default text colour for the main content area. */
        [data-testid="stMain"],
        [data-testid="stMain"] [data-testid="stMarkdownContainer"],
        [data-testid="stMain"] [data-testid="stMarkdownContainer"] p,
        [data-testid="stMain"] [data-testid="stMarkdownContainer"] li,
        [data-testid="stMain"] [data-testid="stMarkdownContainer"] strong,
        [data-testid="stMain"] [data-testid="stMarkdownContainer"] em,
        [data-testid="stMain"] [data-testid="stMarkdownContainer"] h1,
        [data-testid="stMain"] [data-testid="stMarkdownContainer"] h2,
        [data-testid="stMain"] [data-testid="stMarkdownContainer"] h3,
        [data-testid="stMain"] [data-testid="stMarkdownContainer"] h4 {
            color: #f1f5f9;
        }

        /* Captions and helper text in the main area: muted slate. */
        [data-testid="stMain"] [data-testid="stCaptionContainer"],
        [data-testid="stMain"] [data-testid="stCaptionContainer"] * {
            color: #94a3b8;
        }

        /* Markdown links: bright blue, accessible on dark bg. */
        [data-testid="stMain"] [data-testid="stMarkdownContainer"] a {
            color: #60a5fa;
        }
        [data-testid="stMain"] [data-testid="stMarkdownContainer"] a:hover {
            color: #93c5fd;
        }

        /* Dataframes inherit dark-theme styling from Streamlit; ensure the
           radius/clip still apply. */
        [data-testid="stMain"] [data-testid="stDataFrame"] {
            border-radius: 12px;
            overflow: hidden;
        }

        .main-title {
            font-size: 2.4rem;
            font-weight: 800;
            color: #f8fafc;
            margin-bottom: 0.2rem;
        }

        .subtitle {
            font-size: 1rem;
            color: #cbd5e1;
            margin-bottom: 1.5rem;
        }

        /* Sidebar — darker than main bg for clear visual hierarchy. */
        section[data-testid="stSidebar"] {
            background: #020617;
            border-right: 1px solid #1e293b;
        }

        /* Default sidebar text colour. Deliberately NOT `!important` so
           that Streamlit's own component rules can still colour text
           inside lighter-bg controls correctly. */
        section[data-testid="stSidebar"],
        section[data-testid="stSidebar"] p,
        section[data-testid="stSidebar"] span,
        section[data-testid="stSidebar"] li,
        section[data-testid="stSidebar"] h1,
        section[data-testid="stSidebar"] h2,
        section[data-testid="stSidebar"] h3,
        section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"],
        section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] * {
            color: #f1f5f9;
        }

        section[data-testid="stSidebar"] label,
        section[data-testid="stSidebar"] label * {
            color: #e2e8f0 !important;
            font-weight: 600;
        }

        /* Sidebar captions / helper text. `!important` because Streamlit's
           own caption rule otherwise wins the cascade. */
        section[data-testid="stSidebar"] [data-testid="stCaptionContainer"],
        section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] *,
        section[data-testid="stSidebar"] small {
            color: #94a3b8 !important;
        }

        /* Metric cards — dark surface with subtle border. */
        div[data-testid="stMetric"] {
            background: #1e293b;
            border: 1px solid #334155;
            padding: 1rem;
            border-radius: 16px;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
        }

        div[data-testid="stMetric"] label,
        div[data-testid="stMetric"] label * {
            color: #94a3b8 !important;
        }

        div[data-testid="stMetric"] [data-testid="stMetricValue"],
        div[data-testid="stMetric"] [data-testid="stMetricValue"] * {
            color: #f8fafc !important;
        }

        /* Right-column / footer panels. */
        .panel {
            background: #1e293b;
            border-radius: 18px;
            padding: 1.2rem;
            border: 1px solid #334155;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.35);
            margin-bottom: 1rem;
            color: #f1f5f9;
        }

        .panel p,
        .panel li,
        .panel span {
            color: inherit;
        }

        .section-title {
            font-size: 1.25rem;
            font-weight: 750;
            color: #f8fafc;
            margin-bottom: 0.8rem;
        }

        .map-note {
            font-size: 0.9rem;
            color: #94a3b8;
            margin-bottom: 0.6rem;
        }

        /* The Folium choropleth uses the light CartoDB positron tile; keep
           the iframe's rounded corners so the map sits inside a card. */
        iframe {
            border-radius: 18px !important;
        }

        .stDataFrame {
            border-radius: 16px;
            overflow: hidden;
        }

        hr {
            margin-top: 1.5rem;
            margin-bottom: 1.5rem;
            border-color: #334155;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


BOUNDARIES_PATH = "data/london_lsoa_boundaries_clean.geojson"
BOROUGH_BOUNDARIES_PATH = "data/london_borough_boundaries_clean.geojson"
WARD_BOUNDARIES_PATH = "data/london_ward_boundaries_clean.geojson"
WEIGHTS_PATH = "data/category_weights.csv"
LSOA_TO_WARD_PATH = "data/lsoa_to_ward.csv"
CRIME_PATH = ".cache/crime-data/2026-01.csv"

# Approximate London bounding box
LONDON_BOUNDS = [[51.28, -0.52], [51.70, 0.35]]

ANIMATION_FRAME_INTERVAL_MS = 700


# Bump this whenever the load_data return shape or the weights CSV schema
# changes — Streamlit's cache_data keys on parameter values, so changing the
# default forces every running session to reload.
LOAD_DATA_CACHE_VERSION = 5


# Round 3 architecture: per-filter colored GeoJSON files live in
# static/colored/ and are served via Streamlit's enableStaticServing.
# Pydeck's GeoJsonLayer fetches them by URL, so geometry never travels
# through the WebSocket on filter changes.
COLORED_DIR = Path(__file__).parent / "static" / "colored"
COLORED_DIR.mkdir(parents=True, exist_ok=True)

# Streamlit static-file URL prefix. Most recent versions serve at
# `/app/static/<path>`, but local `streamlit run` serves at `/static/<path>`.
# Using a relative URL ("./static/...") lets the browser resolve correctly
# in both cases without us hard-coding which one the deployment uses.
STATIC_URL_PREFIX = "./app/static/colored"


def _stale_colored_cleanup(max_age_seconds: int = 7 * 24 * 3600) -> None:
    """Delete colored GeoJSON files at startup:
    1. Older than max_age_seconds (bounds disk usage), OR
    2. Older than the LSOA boundaries file (geometry has changed since
       these were cached, so the colors are still valid but they were
       built against stale boundary outlines).
    Treats the LSOA file as the canonical geometry-version stamp since
    it changes together with ward/borough whenever the ETL is re-run."""
    now = time.time()
    try:
        boundaries_mtime = (Path(__file__).parent / BOUNDARIES_PATH).stat().st_mtime
    except OSError:
        boundaries_mtime = 0.0

    for path in COLORED_DIR.glob("*.geojson"):
        try:
            mtime = path.stat().st_mtime
            if (now - mtime > max_age_seconds) or (mtime < boundaries_mtime):
                path.unlink()
        except OSError:
            pass


# Streamlit re-executes the entire script on every interaction. Gate the
# cleanup behind st.session_state so the directory scan happens once per
# session, not on every filter change.
if "_colored_cleanup_done" not in st.session_state:
    _stale_colored_cleanup()
    st.session_state["_colored_cleanup_done"] = True


def _filter_fingerprint(*parts) -> str:
    """Stable short hash of filter inputs. Used as the colored-GeoJSON
    filename so the same filter combination resolves to the same URL,
    which lets the browser serve it from HTTP cache on repeat visits."""
    payload = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.md5(payload.encode()).hexdigest()[:16]


@st.cache_data(show_spinner=False)
def load_data(cache_version: int = LOAD_DATA_CACHE_VERSION):
    # Fresh-clone friendly check: name every required output before the
    # first read so a missing file produces a precise, actionable error
    # instead of a raw FileNotFoundError traceback.
    """
    required_files = {
        CRIME_PATH: "Run `python prepare_interactive_data.py` to build it. "
        "Requires `data/london_crime_by_lsoa.csv` to exist first.",
        BOUNDARIES_PATH: "Run `python prepare_interactive_data.py` to regenerate.",
        BOROUGH_BOUNDARIES_PATH: "Run `python prepare_interactive_data.py` to regenerate.",
        WARD_BOUNDARIES_PATH: "Run `python prepare_interactive_data.py` to regenerate.",
        WEIGHTS_PATH: "Run `python prepare_category_weights.py` to build it.",
        LSOA_TO_WARD_PATH: "Run `python prepare_interactive_data.py` to regenerate.",
    }
    from pathlib import Path as _P

    missing = [p for p in required_files if not _P(p).exists()]
    if missing:
        lines = [f"- `{p}` — {required_files[p]}" for p in missing]
        st.error(
            "**Required data file(s) missing — cannot start the dashboard:**\n\n"
            + "\n".join(lines)
            + "\n\nSee the project README for the full data setup."
        )
        st.stop()
    """

    crime_df = Client().street_crimes_timerange(
        2023,
        None,
        exclude_year_month=[
            "2023-01",
            "2023-02",
            "2023-03",
            "2023-04",
            "2023-05",
            "2024-09",
            "2024-10",
            "2025-03",
            "2025-11",
        ],
    )
    boundaries = gpd.read_file(BOUNDARIES_PATH)
    borough_boundaries = gpd.read_file(BOROUGH_BOUNDARIES_PATH)
    ward_boundaries = gpd.read_file(WARD_BOUNDARIES_PATH)
    weights = pd.read_csv(WEIGHTS_PATH).rename(columns={"major_category": "category"})
    lsoa_to_ward = pd.read_csv(LSOA_TO_WARD_PATH)

    crime_df["lsoa_code"] = crime_df["lsoa_code"].astype(str)
    boundaries["lsoa_code"] = boundaries["lsoa_code"].astype(str)
    ward_boundaries["ward_code"] = ward_boundaries["ward_code"].astype(str)
    lsoa_to_ward["lsoa_code"] = lsoa_to_ward["lsoa_code"].astype(str)
    lsoa_to_ward["ward_code"] = lsoa_to_ward["ward_code"].astype(str)

    # Convert low-cardinality string columns to pd.Categorical. With only
    # 9 crime types / 33 boroughs / 4,835 LSOAs across 4M rows, this makes
    # boolean-mask filtering ~3x faster (491ms -> 170ms on a real query).
    # preventability_tier is added after the weights merge below, so it's
    # cast there.
    for col in ("lsoa_code", "borough", "category"):
        if col in crime_df.columns:
            crime_df[col] = crime_df[col].astype("category")

    # Pre-explode MultiPolygons once at load time. Pydeck's GeoJsonLayer
    # is more reliable with single-Polygon rows (see official geopandas
    # integration). Doing it here means we pay the cost once per session
    # instead of on every filter change.
    boundaries = boundaries.explode(index_parts=False, ignore_index=True)
    borough_boundaries = borough_boundaries.explode(index_parts=False, ignore_index=True)
    ward_boundaries = ward_boundaries.explode(index_parts=False, ignore_index=True)

    crime_df = crime_df.merge(weights, on="category", how="left")
    crime_df = crime_df.merge(lsoa_to_ward, on="lsoa_code", how="left")

    # Defensive: a category in crime_df but absent from
    # category_weights.csv. Shouldn't happen in practice once both sources
    # use the same schema, but cheap to guard against.
    unmapped = crime_df["preventability_multiplier"].isna()
    if unmapped.any():
        crime_df.loc[unmapped, "severity_weight_mean"] = 0.0
        crime_df.loc[unmapped, "severity_weight_median"] = 0.0
        crime_df.loc[unmapped, "preventability_multiplier"] = 0.0
        crime_df.loc[unmapped, "preventability_tier"] = "Low"
        crime_df.loc[unmapped, "preventability_confidence"] = "Low"
        crime_df.loc[unmapped, "preventability_anchor"] = "(no anchor)"

    # Categories with no CCHI mapping (e.g., Anti-social behaviour in the
    # 14-schema) keep their preventability values but have NaN severity.
    # Coerce to 0 for arithmetic; a footer caveat names them.
    crime_df["severity_weight_mean"] = crime_df["severity_weight_mean"].fillna(0.0)
    crime_df["severity_weight_median"] = crime_df["severity_weight_median"].fillna(0.0)

    # Categorical cast for preventability_tier — joins the categoricals we
    # set before the weights merge.
    if "preventability_tier" in crime_df.columns:
        crime_df["preventability_tier"] = crime_df["preventability_tier"].astype("category")

    crime_df["severity_weighted_mean"] = crime_df["crime_count"] * crime_df["severity_weight_mean"]
    crime_df["severity_weighted_mean"] = crime_df["crime_count"] * crime_df["severity_weight_mean"]
    crime_df["severity_weighted_median"] = (
        crime_df["crime_count"] * crime_df["severity_weight_median"]
    )
    crime_df["preventability_weighted"] = (
        crime_df["crime_count"] * crime_df["preventability_multiplier"]
    )
    crime_df["composite_weighted_mean"] = (
        crime_df["crime_count"]
        * crime_df["severity_weight_mean"]
        * crime_df["preventability_multiplier"]
    )
    crime_df["composite_weighted_median"] = (
        crime_df["crime_count"]
        * crime_df["severity_weight_median"]
        * crime_df["preventability_multiplier"]
    )

    return (
        crime_df,
        boundaries,
        borough_boundaries,
        ward_boundaries,
        weights,
    )


METRIC_COLUMNS = [
    "crime_count",
    "severity_weighted_mean",
    "severity_weighted_median",
    "preventability_weighted",
    "composite_weighted_mean",
    "composite_weighted_median",
]


@st.cache_data(show_spinner=False)
def compute_map_data(
    _crime_df,
    _boundaries,
    _borough_boundaries,
    _ward_boundaries,
    selected_crime_types: tuple,
    selected_tier: str,
    selected_year,
    selected_months: tuple,
    selected_borough: str,
    aggregation_level: str,
    cache_version: int = LOAD_DATA_CACHE_VERSION,
):
    # Underscored args (_crime_df, _boundaries, ...) are intentionally
    # skipped by Streamlit's hasher — they're large frames cached by
    # load_data() and don't need re-hashing here. cache_version covers
    # invalidation when load_data() changes shape.
    filtered = _crime_df

    if selected_crime_types:
        filtered = filtered[filtered["category"].isin(selected_crime_types)]

    if selected_tier != "All tiers":
        filtered = filtered[filtered["preventability_tier"] == selected_tier]

    if selected_year != "All years":
        filtered = filtered[filtered["year"] == selected_year]

    if selected_months:
        filtered = filtered[filtered["month"].isin(selected_months)]

    if selected_borough != "All boroughs":
        filtered = filtered[filtered["borough"] == selected_borough]

    if aggregation_level == "Borough":
        aggregated = filtered.groupby("borough", as_index=False)[METRIC_COLUMNS].sum()
        map_data = _borough_boundaries.merge(
            aggregated,
            on="borough",
            how="left",
        )
    elif aggregation_level == "Ward":
        aggregated = (
            filtered
            .dropna(subset=["ward_code"])
            .groupby("ward_code", as_index=False)[METRIC_COLUMNS]
            .sum()
        )
        map_data = _ward_boundaries.merge(
            aggregated,
            on="ward_code",
            how="left",
        )
    else:
        aggregated = filtered.groupby("lsoa_code", as_index=False)[METRIC_COLUMNS].sum()
        map_data = _boundaries.merge(
            aggregated,
            on="lsoa_code",
            how="left",
        )

    for column in METRIC_COLUMNS:
        map_data[column] = map_data[column].fillna(0)

    # borough_summary is consumed by the right-column panel. Computing it
    # here means it's cached alongside map_data and the heavy `filtered`
    # frame never leaves this function — important because returning a
    # multi-million-row DataFrame would force a deep copy on every cache
    # hit and erase the perf win.
    borough_summary = (
        filtered
        .groupby("borough", as_index=False)["crime_count"]
        .sum()
        .sort_values("crime_count", ascending=False)
    )

    return map_data, borough_summary


@st.cache_resource(show_spinner=False)
def _cached_base_geojson(
    _boundary_frame,
    level: str,
    cache_version: int = LOAD_DATA_CACHE_VERSION,
) -> dict:
    """Pre-serialize the boundary geometry to a GeoJSON dict ONCE per
    session (per aggregation level). Per-filter color injection then
    becomes deep-copy + dict mutation + json.dumps (~130ms for 4,879
    LSOAs) instead of geopandas .to_json() (~2.3s).

    @st.cache_resource returns the SAME object on every call (no auto
    deep-copy, saves ~80-100ms per filter change). Callers MUST treat
    the returned dict as read-only — prepare_colored_layer explicitly
    deepcopies before mutating.

    The `level` arg is purely a cache-key partitioner."""
    return json.loads(_boundary_frame.to_json())


_ID_COLUMN_BY_LEVEL = {
    "Borough": "borough",
    "Ward": "ward_code",
    "LSOA": "lsoa_code",
}


@st.cache_data(show_spinner=False)
def prepare_colored_layer(
    _map_data,
    _base_geojson: dict,
    selected_metric: str,
    aggregation_level: str,
    filter_inputs: tuple,
    cache_version: int = LOAD_DATA_CACHE_VERSION,
) -> tuple:
    """Inject YlOrRd fill colors into the cached base GeoJSON, slim the
    feature properties for transport, write the result to static/colored/,
    and return `(url, vmin, vmax)`. vmin/vmax are returned so the call
    site can render a legend gradient matching the colormap range.
    Cached on filter_inputs so repeat visits skip both the color compute
    and the file write."""
    import copy

    id_col = _ID_COLUMN_BY_LEVEL[aggregation_level]

    values = _map_data[selected_metric].fillna(0).to_numpy(dtype=float)
    vmin = float(values.min())
    vmax = max(float(values.max()), 1.0)

    rgba = (colormaps["YlOrRd"](Normalize(vmin, vmax)(values)) * 255).astype(np.uint8)
    rgba[:, 3] = 200  # keep 0-value polygons visible (pale yellow)

    # Look-up table from feature id (lsoa_code / ward_code / borough)
    # to the precomputed [r, g, b, a] list.
    id_series = _map_data[id_col].astype(str)
    rgba_lookup = dict(zip(id_series, rgba.tolist()))

    # Also build a metric value lookup so the tooltip stays correct.
    metric_lookup = dict(zip(id_series, _map_data[selected_metric].fillna(0).tolist()))
    count_lookup = dict(zip(id_series, _map_data["crime_count"].fillna(0).tolist()))

    # Deep copy the cached base so we never mutate it (cached objects
    # are shared across reruns — mutation would corrupt other sessions).
    work = copy.deepcopy(_base_geojson)

    grey = [200, 200, 200, 100]
    for feat in work["features"]:
        props = feat["properties"]
        fid = str(props.get(id_col, ""))
        props["fill_color"] = rgba_lookup.get(fid, grey)
        props["crime_count"] = count_lookup.get(fid, 0)
        props[selected_metric] = metric_lookup.get(fid, 0)
        # Drop properties we don't render in the tooltip to keep file small.
        keep_keys = {
            "fill_color",
            "crime_count",
            selected_metric,
            "lsoa_code",
            "lsoa_name",
            "ward_code",
            "ward_name",
            "borough",
        }
        for k in list(props.keys()):
            if k not in keep_keys:
                del props[k]

    # Include cache_version in the fingerprint so an on-disk file from
    # a previous version is treated as a different cache entry and gets
    # rewritten rather than served stale.
    fp = _filter_fingerprint(filter_inputs, selected_metric, aggregation_level, cache_version)
    filename = f"{aggregation_level}_{fp}.geojson"
    path = COLORED_DIR / filename
    if not path.exists():
        try:
            path.write_text(json.dumps(work, separators=(",", ":")), encoding="utf-8")
        except OSError as exc:
            # Disk full / read-only / permission issue. The map still
            # works for this render because pydeck will fetch the URL,
            # 404, and silently render blank — surface a warning so the
            # user knows why colors disappeared, but don't crash.
            st.warning(
                f"Could not cache colored boundaries to disk ({exc}). "
                "Map may render without colors until the issue is fixed."
            )
    return f"{STATIC_URL_PREFIX}/{filename}", vmin, vmax


CONFIDENCE_EMOJI = {"High": "🟢", "Medium": "🟡", "Low": "🔴"}


def create_map(
    map_data,
    selected_metric,
    selected_borough,
    aggregation_level,
    metric_caption,
    use_pydeck=True,
    data_url=None,
):
    if use_pydeck:
        return _create_map_pydeck(
            data_url=data_url,
            map_data=map_data,
            selected_metric=selected_metric,
            selected_borough=selected_borough,
            aggregation_level=aggregation_level,
            metric_caption=metric_caption,
        )
    return _create_map_folium(
        map_data,
        selected_metric,
        selected_borough,
        aggregation_level,
        metric_caption,
    )


def _create_map_pydeck(
    data_url: str,
    map_data,  # used only for borough_area.total_bounds
    selected_metric,
    selected_borough,
    aggregation_level,
    metric_caption,
):
    # Guard against silent blank maps: if data_url is None, pydeck
    # serializes a GeoJsonLayer with no data field and the layer renders
    # empty. Surface a clear failure to the caller instead.
    if not data_url:
        raise ValueError(
            "_create_map_pydeck requires a non-empty data_url. Did "
            "prepare_colored_layer fail or get skipped?"
        )

    # Round 3: geometry + colors live in the file at data_url. The browser
    # fetches and HTTP-caches it. Per-render the Deck JSON only carries
    # the URL string (~500 bytes), not the 10MB GeoJSON payload.
    view_state = pdk.ViewState(
        latitude=51.5074,
        longitude=-0.1278,
        zoom=10,
        min_zoom=9,
        max_zoom=15,
    )

    if selected_borough != "All boroughs" and not map_data.empty:
        borough_area = map_data[map_data["borough"] == selected_borough]
        if not borough_area.empty:
            minx, miny, maxx, maxy = borough_area.total_bounds
            view_state.latitude = (miny + maxy) / 2
            view_state.longitude = (minx + maxx) / 2
            view_state.zoom = 11.5

    if aggregation_level == "Borough":
        tooltip_html = (
            "<b>Borough:</b> {borough}<br/>"
            "<b>Crime count:</b> {crime_count}<br/>"
            f"<b>Displayed value:</b> {{{selected_metric}}}"
        )
    elif aggregation_level == "Ward":
        tooltip_html = (
            "<b>Ward:</b> {ward_name}<br/>"
            "<b>Borough:</b> {borough}<br/>"
            "<b>Crime count:</b> {crime_count}<br/>"
            f"<b>Displayed value:</b> {{{selected_metric}}}"
        )
    else:
        tooltip_html = (
            "<b>LSOA:</b> {lsoa_name}<br/>"
            "<b>Borough:</b> {borough}<br/>"
            "<b>Crime count:</b> {crime_count}<br/>"
            f"<b>Displayed value:</b> {{{selected_metric}}}"
        )

    tooltip = {
        "html": tooltip_html,
        "style": {
            "backgroundColor": "rgba(255, 255, 255, 0.96)",
            "color": "#111827",
            "border": "1px solid #d1d5db",
            "borderRadius": "10px",
            "padding": "10px",
            "boxShadow": "0 8px 24px rgba(15, 23, 42, 0.18)",
            "fontSize": "13px",
            "fontFamily": "Arial, sans-serif",
        },
    }

    layer = pdk.Layer(
        "GeoJsonLayer",
        data=data_url,  # URL, not GeoDataFrame
        get_fill_color="properties.fill_color",  # reads baked colors
        get_line_color=[255, 255, 255, 64],
        line_width_min_pixels=0.25,
        pickable=True,
        auto_highlight=True,
        highlight_color=[17, 24, 39, 220],
    )

    return pdk.Deck(
        layers=[layer],
        initial_view_state=view_state,
        map_style=pdk.map_styles.CARTO_LIGHT,
        tooltip=tooltip,
    )


def _create_map_folium(
    map_data,
    selected_metric,
    selected_borough,
    aggregation_level,
    metric_caption,
):
    m = folium.Map(
        location=[51.5074, -0.1278],
        zoom_start=10,
        min_zoom=9,
        max_zoom=15,
        tiles=None,
        max_bounds=True,
        control_scale=True,
    )

    folium.TileLayer(tiles="CartoDB positron", name="Light map", control=False).add_to(m)

    # Restrict panning to London
    m.fit_bounds(LONDON_BOUNDS)

    sw, ne = LONDON_BOUNDS
    m.options["maxBounds"] = [sw, ne]
    m.options["maxBoundsViscosity"] = 1.0

    values = map_data[selected_metric].fillna(0)

    min_value = float(values.min())
    max_value = float(values.max())

    if max_value <= 0:
        max_value = 1

    colormap = cm.linear.YlOrRd_09.scale(min_value, max_value)
    colormap.caption = metric_caption

    def style_function(feature):
        value = feature["properties"].get(selected_metric, 0)

        if value is None:
            value = 0

        return {
            "fillColor": colormap(value),
            "color": "#ffffff",
            "weight": 0.25,
            "fillOpacity": 0.78,
        }

    def highlight_function(feature):
        return {
            "fillColor": "#111827",
            "color": "#111827",
            "weight": 1.2,
            "fillOpacity": 0.88,
        }

    if aggregation_level == "Borough":
        tooltip_fields = ["borough", "crime_count", selected_metric]
        tooltip_aliases = ["Borough:", "Crime count:", "Displayed value:"]
    elif aggregation_level == "Ward":
        tooltip_fields = ["ward_name", "borough", "crime_count", selected_metric]
        tooltip_aliases = [
            "Ward:",
            "Borough:",
            "Crime count:",
            "Displayed value:",
        ]
    else:
        tooltip_fields = [
            "lsoa_name",
            "borough",
            "crime_count",
            selected_metric,
        ]
        tooltip_aliases = [
            "LSOA:",
            "Borough:",
            "Crime count:",
            "Displayed value:",
        ]

    tooltip = folium.GeoJsonTooltip(
        fields=tooltip_fields,
        aliases=tooltip_aliases,
        localize=True,
        sticky=True,
        labels=True,
        style="""
            background-color: rgba(255, 255, 255, 0.96);
            color: #111827;
            border: 1px solid #d1d5db;
            border-radius: 10px;
            padding: 10px;
            box-shadow: 0 8px 24px rgba(15, 23, 42, 0.18);
            font-size: 13px;
            font-family: Arial, sans-serif;
        """,
    )

    folium.GeoJson(
        data=map_data.to_json(),
        name="Crime by LSOA",
        style_function=style_function,
        highlight_function=highlight_function,
        tooltip=tooltip,
        smooth_factor=1.2,
    ).add_to(m)

    colormap.add_to(m)

    # If a borough is selected, zoom closer to that borough
    if selected_borough != "All boroughs" and not map_data.empty:
        borough_area = map_data[map_data["borough"] == selected_borough]

        if not borough_area.empty:
            minx, miny, maxx, maxy = borough_area.total_bounds
            m.fit_bounds([[miny, minx], [maxy, maxx]])

    return m


(
    crime_df,
    boundaries,
    borough_boundaries,
    ward_boundaries,
    weights,
) = load_data(cache_version=LOAD_DATA_CACHE_VERSION)

confidence_by_category = dict(zip(weights["category"], weights["preventability_confidence"]))
anchor_by_category = dict(zip(weights["category"], weights["preventability_anchor"]))


def format_crime_type(category: str) -> str:
    """Prefix the category name with a confidence dot for the multiselect."""
    confidence = confidence_by_category.get(category, "Low")
    emoji = CONFIDENCE_EMOJI.get(confidence, "⚪")
    return f"{emoji} {category}"


year_month_pairs = sorted(
    crime_df[["year", "month"]].drop_duplicates().itertuples(index=False, name=None)
)


def format_period(pair):
    return f"{pair[0]}-{pair[1]:02d}"


if "playing" not in st.session_state:
    st.session_state.playing = False

if "period_idx" not in st.session_state:
    st.session_state.period_idx = 0

if "anim_tick" not in st.session_state:
    st.session_state.anim_tick = 0

last_seen_tick = st.session_state.get("_seen_anim_tick", 0)
if st.session_state.playing and st.session_state.anim_tick > last_seen_tick:
    next_idx = st.session_state.period_idx + 1
    if next_idx >= len(year_month_pairs):
        st.session_state.playing = False
    else:
        st.session_state.period_idx = next_idx
    st.session_state._seen_anim_tick = st.session_state.anim_tick

st.session_state.period_idx = min(st.session_state.period_idx, len(year_month_pairs) - 1)


@st.fragment(run_every=(f"{ANIMATION_FRAME_INTERVAL_MS}ms" if st.session_state.playing else None))
def _animation_tick():
    if st.session_state.playing:
        st.session_state.anim_tick += 1
        st.rerun(scope="app")


# -----------------------------
# Header
# -----------------------------

st.markdown(
    """
    <div class="main-title">London Crime Explorer</div>
    <div class="subtitle">
        Explore recorded crime patterns across London LSOAs using crime type, year, month, and borough filters.
    </div>
    """,
    unsafe_allow_html=True,
)


# -----------------------------
# Sidebar filters
# -----------------------------

with st.sidebar:
    st.header("Filters")

    crime_types = sorted(crime_df["category"].dropna().unique())

    selected_crime_types = st.multiselect(
        "Crime type",
        options=crime_types,
        default=crime_types,
        format_func=format_crime_type,
        help="🟢/🟡/🔴 dots indicate evidence strength of the preventability "
        "multiplier (see footer). Empty selection counts as all crime "
        "types.",
    )

    st.caption(
        "🟢 High &nbsp;·&nbsp; 🟡 Medium &nbsp;·&nbsp; 🔴 Low confidence "
        "in preventability multiplier"
    )

    selected_tier = st.selectbox(
        "Preventability tier",
        options=["All tiers", "High", "Medium", "Low"],
        help="Tiers are defined in data/category_weights.csv "
        "and reflect how responsive each crime type is to visible "
        "patrol presence.",
    )

    animate = st.checkbox(
        "Animate over time",
        value=False,
        help="Replaces the year + month filters with a single play "
        "control that steps through every month in the dataset.",
    )

    if animate:
        idx = st.select_slider(
            "Period",
            options=list(range(len(year_month_pairs))),
            key="period_idx",
            format_func=lambda i: format_period(year_month_pairs[i]),
        )

        play_col, reset_col = st.columns(2)

        with play_col:
            if st.session_state.playing:
                if st.button("⏸ Pause", use_container_width=True):
                    st.session_state.playing = False
                    st.rerun()
            else:
                if st.button("▶ Play", use_container_width=True):
                    st.session_state.playing = True
                    st.rerun()

        with reset_col:
            if st.button("⏮ Reset", use_container_width=True):
                st.session_state.period_idx = 0
                st.session_state.playing = False
                st.rerun()

        selected_year, selected_month = year_month_pairs[idx]
        selected_months = [selected_month]
    else:
        st.session_state.playing = False

        years = sorted(crime_df["year"].dropna().unique())

        selected_year = st.selectbox("Year", options=["All years"] + list(years))

        selected_months = st.multiselect(
            "Month", options=list(range(1, 13)), default=list(range(1, 13))
        )
    selected_crime_type = st.selectbox("Crime type", options=["All crime types"] + crime_types)

    boroughs = sorted(crime_df["borough"].dropna().unique())

    selected_borough = st.selectbox("Borough", options=["All boroughs"] + boroughs)

    st.markdown("---")

    aggregation_level = st.radio(
        "Aggregation level", options=["LSOA", "Ward", "Borough"], horizontal=True
    )

    severity_basis = st.radio(
        "Severity basis",
        options=["Mean CCHI", "Median CCHI"],
        index=0,
        horizontal=True,
        help="CCHI offences vary in severity within a category. Mean "
        "preserves the Σ count × score identity; median is more "
        "representative of the typical offence and is robust to the "
        "long-tailed within-category mix. Affects Severity-weighted "
        "and Composite map modes.",
    )

    use_pydeck = st.toggle(
        "New map engine (beta)",
        value=True,
        help="Pydeck (GPU-accelerated via deck.gl/WebGL). Renders ~5,000 "
        "LSOA polygons at 30+ fps versus Folium's ~0.5 fps. Disable "
        "to fall back to the original Folium map.",
    )

    classification_mode = st.radio(
        "Map mode",
        options=[
            "Raw crime count",
            "Crime share within selected data",
            "Severity-weighted",
            "Preventability-filtered",
            "Composite (severity x preventability)",
        ],
    )


# -----------------------------
# Filtering (cached on filter inputs — toggling map mode / severity basis
# is now a free cache hit because those don't affect map_data shape)
# -----------------------------

map_data, borough_summary = compute_map_data(
    crime_df,
    boundaries,
    borough_boundaries,
    ward_boundaries,
    selected_crime_types=tuple(selected_crime_types),
    selected_tier=selected_tier,
    selected_year=selected_year,
    selected_months=tuple(selected_months),
    selected_borough=selected_borough,
    aggregation_level=aggregation_level,
    cache_version=LOAD_DATA_CACHE_VERSION,
)

basis_suffix = "mean" if severity_basis == "Mean CCHI" else "median"

METRIC_BY_MODE = {
    "Raw crime count": ("crime_count", "Recorded crime count"),
    "Severity-weighted": (
        f"severity_weighted_{basis_suffix}",
        f"Severity-weighted crime count ({severity_basis})",
    ),
    "Preventability-filtered": ("preventability_weighted", "Preventability-weighted crime count"),
    "Composite (severity x preventability)": (
        f"composite_weighted_{basis_suffix}",
        f"Composite severity × preventability ({severity_basis})",
    ),
}

if classification_mode == "Crime share within selected data":
    total_selected_crime = map_data["crime_count"].sum()

    if total_selected_crime > 0:
        map_data["crime_share"] = (map_data["crime_count"] / total_selected_crime) * 100
    else:
        map_data["crime_share"] = 0

    selected_metric = "crime_share"
    metric_caption = "Crime share within selected data (%)"
else:
    selected_metric, metric_caption = METRIC_BY_MODE[classification_mode]


# -----------------------------
# Summary values
# -----------------------------

total_crimes = int(map_data["crime_count"].sum())
active_units = int((map_data["crime_count"] > 0).sum())
average_per_unit = round(map_data["crime_count"].mean(), 2)

if aggregation_level == "Borough":
    top_units_columns = ["borough", "crime_count"]
    top_units_label = "Top 10 boroughs"
    active_units_label = "Boroughs with crimes"
    average_label = "Average per borough"
elif aggregation_level == "Ward":
    top_units_columns = ["ward_code", "ward_name", "borough", "crime_count"]
    top_units_label = "Top 10 wards"
    active_units_label = "Wards with crimes"
    average_label = "Average per ward"
else:
    top_units_columns = ["lsoa_code", "lsoa_name", "borough", "crime_count"]
    top_units_label = "Top 10 LSOAs"
    active_units_label = "LSOAs with crimes"
    average_label = "Average per LSOA"

top_units = map_data[top_units_columns]


top_lsoas = (
    map_data[["lsoa_code", "lsoa_name", "borough", "crime_count"]]
    .sort_values("crime_count", ascending=False)
    .head(10)
)

# borough_summary is now returned by compute_map_data() above (cached).


# -----------------------------
# Main layout
# -----------------------------

metric_col_1, metric_col_2, metric_col_3 = st.columns(3)

with metric_col_1:
    st.metric("Total selected crimes", f"{total_crimes:,}")

with metric_col_2:
    st.metric(active_units_label, f"{active_units:,}")

with metric_col_3:
    st.metric(average_label, f"{average_per_unit:,}")


left_col, right_col = st.columns([3.2, 1.2])

with left_col:
    st.markdown(
        """
        <div class="panel">
            <div class="section-title">Interactive London map</div>
            <div class="map-note">
                The map is locked to London. Hover over an area to inspect its crime count.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Build a stable fingerprint of all filter inputs so the colored
    # GeoJSON file is reused (and browser-cached) for the same combo.
    filter_inputs = (
        tuple(selected_crime_types),
        selected_tier,
        selected_year,
        tuple(selected_months),
        selected_borough,
        aggregation_level,
    )

    data_url = None
    legend_vmin = legend_vmax = None
    if use_pydeck:
        # Pick the right boundary frame for the aggregation level, then
        # fetch its pre-serialized GeoJSON dict (cached for the session).
        # Geometry serialization happens ONCE per session, not per filter.
        if aggregation_level == "Borough":
            _bf = borough_boundaries
        elif aggregation_level == "Ward":
            _bf = ward_boundaries
        else:
            _bf = boundaries
        base_geojson = _cached_base_geojson(
            _bf,
            aggregation_level,
            cache_version=LOAD_DATA_CACHE_VERSION,
        )

        # Writes the colored file under static/colored/ if missing and
        # returns (url, vmin, vmax). Cached on filter_inputs so repeat
        # visits skip both the color compute and the file write.
        data_url, legend_vmin, legend_vmax = prepare_colored_layer(
            map_data,
            base_geojson,
            selected_metric,
            aggregation_level,
            filter_inputs,
            cache_version=LOAD_DATA_CACHE_VERSION,
        )

    crime_map = create_map(
        map_data=map_data,
        selected_metric=selected_metric,
        selected_borough=selected_borough,
        aggregation_level=aggregation_level,
        metric_caption=metric_caption,
        use_pydeck=use_pydeck,
        data_url=data_url,
    )

    if use_pydeck:
        # The stable `key=` is critical: without it, every @st.fragment
        # tick remounts the deck.gl canvas and wipes the perf gain.
        st.pydeck_chart(
            crime_map,
            use_container_width=True,
            height=720,
            key="crime_map",
        )
        # Color legend — pydeck has no native legend, so we render a
        # YlOrRd CSS gradient with the actual vmin/vmax of the rendered
        # metric. Matches the colormap inside prepare_colored_layer.
        if legend_vmin is not None and legend_vmax is not None:
            st.markdown(
                f"""
                <div class="panel" style="margin-top: 12px; padding: 14px 18px;">
                    <div style="font-size: 0.85rem; color: #cbd5f5; margin-bottom: 6px;">
                        {metric_caption}
                    </div>
                    <div style="
                        height: 14px;
                        border-radius: 7px;
                        background: linear-gradient(to right,
                            #ffffb2, #fed976, #feb24c, #fd8d3c,
                            #fc4e2a, #e31a1c, #b10026);
                        border: 1px solid rgba(255,255,255,0.08);
                    "></div>
                    <div style="
                        display: flex;
                        justify-content: space-between;
                        font-size: 0.78rem;
                        color: #94a3b8;
                        margin-top: 4px;
                        font-variant-numeric: tabular-nums;
                    ">
                        <span>{legend_vmin:,.1f}</span>
                        <span>{legend_vmax:,.1f}</span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    else:
        st_folium(crime_map, use_container_width=True, height=720, returned_objects=[])


with right_col:
    st.markdown(
        f"""
        <div class="panel">
            <div class="section-title">{top_units_label}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.dataframe(top_units, use_container_width=True, hide_index=True)

    st.markdown(
        """
        <div class="panel">
            <div class="section-title">Current selection</div>
            <p style="color:#6b7280; margin-bottom:0;">
                Use this panel to check whether the filters are producing the expected subset.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if selected_crime_types and len(selected_crime_types) < len(crime_types):
        crime_type_label = ", ".join(selected_crime_types)
    else:
        crime_type_label = "All crime types"

    if animate:
        period_label = format_period(year_month_pairs[st.session_state.period_idx])
        st.write(f"**Period:** {period_label} (animated)")
    else:
        st.write(f"**Year:** {selected_year}")
        st.write(f"**Months selected:** {len(selected_months)}")

    st.write(f"**Crime types:** {crime_type_label}")
    st.write(f"**Tier:** {selected_tier}")
    st.write(f"**Borough:** {selected_borough}")
    st.write(f"**Aggregation level:** {aggregation_level}")
    st.write(f"**Severity basis:** {severity_basis}")
    st.write(f"**Map mode:** {classification_mode}")

    st.markdown(
        """
        <div class="panel">
            <div class="section-title">Selected category sources</div>
            <p style="color:#6b7280; margin-bottom:0;">
                Confidence rating and one-line literature anchor per
                selected crime type. Used to defend the multiplier choice
                in the dashboard.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    visible_categories = selected_crime_types if selected_crime_types else crime_types

    sources_rows = []
    for category in visible_categories:
        confidence = confidence_by_category.get(category, "Low")
        anchor = anchor_by_category.get(category, "(no anchor)")
        sources_rows.append({
            "": CONFIDENCE_EMOJI.get(confidence, "⚪"),
            "Category": category,
            "Confidence": confidence,
            "Anchor": anchor,
        })

    st.dataframe(
        pd.DataFrame(sources_rows),
        use_container_width=True,
        hide_index=True,
    )


st.markdown("---")

st.markdown("### Borough summary")

st.dataframe(borough_summary, use_container_width=True, hide_index=True)

st.markdown(
    f"**Severity weights** come from the Cambridge Crime Harm Index "
    f"(CCHI) 2020 — currently set to **{severity_basis}** of CCHI scores "
    f"across each category's offences. Toggle the basis in the sidebar. "
    f"Both bases are uniform-weighted across CCHI offence definitions "
    f"(per-offence frequencies aren't published, so the within-category "
    f"offence mix is treated as uniform). CCHI is defined per offence code "
    f"while the dataset stores major-category aggregates, so a single "
    f"category's weight pools offences of different severities — e.g., a "
    f'"Violence" weight pools common assault with more serious offences. '
    f"Anti-social behaviour is non-notifiable and outside CCHI's scope; "
    f"its severity is treated as 0 in severity-weighted modes."
)

st.markdown(
    "**Preventability multipliers** are anchored in the literature: "
    "[Braga et al. 2019](https://doi.org/10.4073/csr.2019.3) (Campbell SR "
    "meta-analysis of hot-spot policing — disorder ES = 0.161, drug crime "
    "ES = 0.244, violent crime ES = 0.102), "
    "[Weisburd 2015](https://doi.org/10.1111/1745-9125.12070) (crime "
    "concentration: 100% of robberies in 2.2% of places, 100% of vehicle "
    "crime in 2.7%), Weisburd 2021 (MIT Press review of presence vs "
    "response), and Sherman, Neyroud & Neyroud 2016 (CCHI methodology). "
    "Each row's one-line citation is shown in the *Selected category "
    "sources* panel. Confidence (🟢 High / 🟡 Medium / 🔴 Low) reflects "
    "evidence strength per category — categories flagged 🔴 should be "
    "interpreted with care."
)

st.caption(
    "Re-run `prepare_category_weights.py` after editing CCHI mappings or "
    "preventability values. The script auto-detects whether the current "
    "raw data is the legacy 9-category MPS taxonomy or the 14-category "
    "data.police.uk taxonomy and emits a matching weights CSV."
)


_animation_tick()
