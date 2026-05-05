import pandas as pd
import geopandas as gpd
import streamlit as st
import folium
from streamlit_folium import st_folium
import branca.colormap as cm


st.set_page_config(
    page_title="London Crime Explorer",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded"
)


# -----------------------------
# Custom CSS
# -----------------------------

st.markdown(
    """
    <style>
        .stApp {
            background: linear-gradient(180deg, #f7f8fb 0%, #eef1f6 100%);
        }

        .main-title {
            font-size: 2.4rem;
            font-weight: 800;
            color: #111827;
            margin-bottom: 0.2rem;
        }

        .subtitle {
            font-size: 1rem;
            color: #6b7280;
            margin-bottom: 1.5rem;
        }

        section[data-testid="stSidebar"] {
            background: #111827;
        }

        section[data-testid="stSidebar"] * {
            color: #f9fafb;
        }

        section[data-testid="stSidebar"] label {
            color: #e5e7eb !important;
            font-weight: 600;
        }

        div[data-testid="stMetric"] {
            background: white;
            border: 1px solid #e5e7eb;
            padding: 1rem;
            border-radius: 16px;
            box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
        }

        div[data-testid="stMetric"] label {
            color: #6b7280 !important;
        }

        div[data-testid="stMetric"] div {
            color: #111827 !important;
        }

        .panel {
            background: white;
            border-radius: 18px;
            padding: 1.2rem;
            border: 1px solid #e5e7eb;
            box-shadow: 0 10px 30px rgba(15, 23, 42, 0.07);
            margin-bottom: 1rem;
        }

        .section-title {
            font-size: 1.25rem;
            font-weight: 750;
            color: #111827;
            margin-bottom: 0.8rem;
        }

        .map-note {
            font-size: 0.9rem;
            color: #6b7280;
            margin-bottom: 0.6rem;
        }

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
        }
    </style>
    """,
    unsafe_allow_html=True
)


BOUNDARIES_PATH = "outputs/london_lsoa_boundaries_clean.geojson"
BOROUGH_BOUNDARIES_PATH = "outputs/london_borough_boundaries_clean.geojson"
CRIME_PATH = "outputs/crime_aggregated_for_app.csv"
WEIGHTS_PATH = "data/category_weights.csv"

# Approximate London bounding box
LONDON_BOUNDS = [
    [51.28, -0.52],
    [51.70, 0.35]
]

ANIMATION_FRAME_INTERVAL_MS = 700


@st.cache_data
def load_data():
    crime_df = pd.read_csv(CRIME_PATH)
    boundaries = gpd.read_file(BOUNDARIES_PATH)
    borough_boundaries = gpd.read_file(BOROUGH_BOUNDARIES_PATH)
    weights = pd.read_csv(WEIGHTS_PATH)

    crime_df["lsoa_code"] = crime_df["lsoa_code"].astype(str)
    boundaries["lsoa_code"] = boundaries["lsoa_code"].astype(str)

    crime_df = crime_df.merge(weights, on="major_category", how="left")

    missing_weights = crime_df["severity_weight"].isna()
    if missing_weights.any():
        crime_df.loc[missing_weights, "severity_weight"] = 1.0
        crime_df.loc[missing_weights, "preventability_multiplier"] = 0.0
        crime_df.loc[missing_weights, "preventability_tier"] = "Low"

    crime_df["severity_weighted"] = (
        crime_df["crime_count"] * crime_df["severity_weight"]
    )
    crime_df["preventability_weighted"] = (
        crime_df["crime_count"] * crime_df["preventability_multiplier"]
    )
    crime_df["composite_weighted"] = (
        crime_df["crime_count"]
        * crime_df["severity_weight"]
        * crime_df["preventability_multiplier"]
    )

    return crime_df, boundaries, borough_boundaries


def create_map(
    map_data,
    selected_metric,
    selected_borough,
    aggregation_level,
    metric_caption
):
    m = folium.Map(
        location=[51.5074, -0.1278],
        zoom_start=10,
        min_zoom=9,
        max_zoom=15,
        tiles=None,
        max_bounds=True,
        control_scale=True
    )

    folium.TileLayer(
        tiles="CartoDB positron",
        name="Light map",
        control=False
    ).add_to(m)

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
        """
    )

    folium.GeoJson(
        data=map_data.to_json(),
        name="Crime by LSOA",
        style_function=style_function,
        highlight_function=highlight_function,
        tooltip=tooltip,
        smooth_factor=1.2
    ).add_to(m)

    colormap.add_to(m)

    # If a borough is selected, zoom closer to that borough
    if selected_borough != "All boroughs" and not map_data.empty:
        borough_area = map_data[map_data["borough"] == selected_borough]

        if not borough_area.empty:
            minx, miny, maxx, maxy = borough_area.total_bounds
            m.fit_bounds([[miny, minx], [maxy, maxx]])

    return m


crime_df, boundaries, borough_boundaries = load_data()

year_month_pairs = sorted(
    crime_df[["year", "month"]]
    .drop_duplicates()
    .itertuples(index=False, name=None)
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
if (
    st.session_state.playing
    and st.session_state.anim_tick > last_seen_tick
):
    next_idx = st.session_state.period_idx + 1
    if next_idx >= len(year_month_pairs):
        st.session_state.playing = False
    else:
        st.session_state.period_idx = next_idx
    st.session_state._seen_anim_tick = st.session_state.anim_tick

st.session_state.period_idx = min(
    st.session_state.period_idx,
    len(year_month_pairs) - 1
)


@st.fragment(
    run_every=(
        f"{ANIMATION_FRAME_INTERVAL_MS}ms"
        if st.session_state.playing
        else None
    )
)
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
    unsafe_allow_html=True
)


# -----------------------------
# Sidebar filters
# -----------------------------

with st.sidebar:
    st.header("Filters")

    crime_types = sorted(crime_df["major_category"].dropna().unique())

    selected_crime_types = st.multiselect(
        "Crime type",
        options=crime_types,
        default=crime_types,
        help="Empty selection counts as all crime types."
    )

    selected_tier = st.selectbox(
        "Preventability tier",
        options=["All tiers", "High", "Medium", "Low"],
        help="Tiers are defined in data/category_weights.csv "
             "and reflect how responsive each crime type is to visible "
             "patrol presence."
    )

    animate = st.checkbox(
        "Animate over time",
        value=False,
        help="Replaces the year + month filters with a single play "
             "control that steps through every month in the dataset."
    )

    if animate:
        idx = st.select_slider(
            "Period",
            options=list(range(len(year_month_pairs))),
            key="period_idx",
            format_func=lambda i: format_period(year_month_pairs[i])
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

        selected_year = st.selectbox(
            "Year",
            options=["All years"] + list(years)
        )

        selected_months = st.multiselect(
            "Month",
            options=list(range(1, 13)),
            default=list(range(1, 13))
        )

    boroughs = sorted(crime_df["borough"].dropna().unique())

    selected_borough = st.selectbox(
        "Borough",
        options=["All boroughs"] + boroughs
    )

    st.markdown("---")

    aggregation_level = st.radio(
        "Aggregation level",
        options=["LSOA", "Borough"],
        horizontal=True
    )

    classification_mode = st.radio(
        "Map mode",
        options=[
            "Raw crime count",
            "Crime share within selected data",
            "Severity-weighted",
            "Preventability-filtered",
            "Composite (severity x preventability)"
        ]
    )


# -----------------------------
# Filtering
# -----------------------------

filtered = crime_df.copy()

if selected_crime_types:
    filtered = filtered[filtered["major_category"].isin(selected_crime_types)]

if selected_tier != "All tiers":
    filtered = filtered[filtered["preventability_tier"] == selected_tier]

if selected_year != "All years":
    filtered = filtered[filtered["year"] == selected_year]

if selected_months:
    filtered = filtered[filtered["month"].isin(selected_months)]

if selected_borough != "All boroughs":
    filtered = filtered[filtered["borough"] == selected_borough]


METRIC_COLUMNS = [
    "crime_count",
    "severity_weighted",
    "preventability_weighted",
    "composite_weighted",
]

if aggregation_level == "Borough":
    aggregated = (
        filtered
        .groupby("borough", as_index=False)[METRIC_COLUMNS]
        .sum()
    )
    map_data = borough_boundaries.merge(
        aggregated,
        on="borough",
        how="left"
    )
else:
    aggregated = (
        filtered
        .groupby("lsoa_code", as_index=False)[METRIC_COLUMNS]
        .sum()
    )
    map_data = boundaries.merge(
        aggregated,
        on="lsoa_code",
        how="left"
    )

for column in METRIC_COLUMNS:
    map_data[column] = map_data[column].fillna(0)


METRIC_BY_MODE = {
    "Raw crime count": ("crime_count", "Recorded crime count"),
    "Severity-weighted": (
        "severity_weighted",
        "Severity-weighted crime count"
    ),
    "Preventability-filtered": (
        "preventability_weighted",
        "Preventability-weighted crime count"
    ),
    "Composite (severity x preventability)": (
        "composite_weighted",
        "Composite (severity x preventability) score"
    ),
}

if classification_mode == "Crime share within selected data":
    total_selected_crime = map_data["crime_count"].sum()

    if total_selected_crime > 0:
        map_data["crime_share"] = (
            map_data["crime_count"] / total_selected_crime
        ) * 100
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
else:
    top_units_columns = ["lsoa_code", "lsoa_name", "borough", "crime_count"]
    top_units_label = "Top 10 LSOAs"
    active_units_label = "LSOAs with crimes"
    average_label = "Average per LSOA"

top_units = (
    map_data[top_units_columns]
    .sort_values("crime_count", ascending=False)
    .head(10)
)

borough_summary = (
    filtered
    .groupby("borough", as_index=False)["crime_count"]
    .sum()
    .sort_values("crime_count", ascending=False)
)


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
        unsafe_allow_html=True
    )

    crime_map = create_map(
        map_data=map_data,
        selected_metric=selected_metric,
        selected_borough=selected_borough,
        aggregation_level=aggregation_level,
        metric_caption=metric_caption
    )

    st_folium(
        crime_map,
        use_container_width=True,
        height=720,
        returned_objects=[]
    )


with right_col:
    st.markdown(
        f"""
        <div class="panel">
            <div class="section-title">{top_units_label}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.dataframe(
        top_units,
        use_container_width=True,
        hide_index=True
    )

    st.markdown(
        """
        <div class="panel">
            <div class="section-title">Current selection</div>
            <p style="color:#6b7280; margin-bottom:0;">
                Use this panel to check whether the filters are producing the expected subset.
            </p>
        </div>
        """,
        unsafe_allow_html=True
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
    st.write(f"**Map mode:** {classification_mode}")


st.markdown("---")

st.markdown("### Borough summary")

st.dataframe(
    borough_summary,
    use_container_width=True,
    hide_index=True
)

st.caption(
    "Severity weights are derived from the Cambridge Crime Harm Index (CCHI) "
    "2020 update — each weight is the offence-count-weighted mean CCHI score "
    "(in days of recommended sentence) across all CCHI offences that map to a "
    "given major_category. Severity-weighted values can therefore be read as "
    "approximate harm-days. Because CCHI is defined per offence code while the "
    "underlying dataset only stores 9 major categories, single-category weights "
    "mix offences of different severity (e.g., \"Violence Against the Person\" "
    "pools common assault with more serious offences). Preventability "
    "multipliers are still placeholder values from the expansion spec's first "
    "pass — sub-question 4 will replace them. Re-run "
    "`prepare_category_weights.py` after editing either source."
)


_animation_tick()
