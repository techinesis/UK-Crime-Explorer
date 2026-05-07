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
    unsafe_allow_html=True
)


BOUNDARIES_PATH = "outputs/london_lsoa_boundaries_clean.geojson"
BOROUGH_BOUNDARIES_PATH = "outputs/london_borough_boundaries_clean.geojson"
WARD_BOUNDARIES_PATH = "outputs/london_ward_boundaries_clean.geojson"
CRIME_PATH = "outputs/crime_aggregated_for_app.csv"
WEIGHTS_PATH = "data/category_weights.csv"
LSOA_TO_WARD_PATH = "outputs/lsoa_to_ward.csv"

# Approximate London bounding box
LONDON_BOUNDS = [
    [51.28, -0.52],
    [51.70, 0.35]
]

ANIMATION_FRAME_INTERVAL_MS = 700


# Bump this whenever the load_data return shape or the weights CSV schema
# changes — Streamlit's cache_data keys on parameter values, so changing the
# default forces every running session to reload.
LOAD_DATA_CACHE_VERSION = 2


@st.cache_data(show_spinner=False)
def load_data(cache_version: int = LOAD_DATA_CACHE_VERSION):
    crime_df = pd.read_csv(CRIME_PATH)
    boundaries = gpd.read_file(BOUNDARIES_PATH)
    borough_boundaries = gpd.read_file(BOROUGH_BOUNDARIES_PATH)
    ward_boundaries = gpd.read_file(WARD_BOUNDARIES_PATH)
    weights = pd.read_csv(WEIGHTS_PATH)
    lsoa_to_ward = pd.read_csv(LSOA_TO_WARD_PATH)

    crime_df["lsoa_code"] = crime_df["lsoa_code"].astype(str)
    boundaries["lsoa_code"] = boundaries["lsoa_code"].astype(str)
    ward_boundaries["ward_code"] = ward_boundaries["ward_code"].astype(str)
    lsoa_to_ward["lsoa_code"] = lsoa_to_ward["lsoa_code"].astype(str)
    lsoa_to_ward["ward_code"] = lsoa_to_ward["ward_code"].astype(str)

    crime_df = crime_df.merge(weights, on="major_category", how="left")
    crime_df = crime_df.merge(lsoa_to_ward, on="lsoa_code", how="left")

    # Defensive: a major_category in crime_df but absent from
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

    crime_df["severity_weighted_mean"] = (
        crime_df["crime_count"] * crime_df["severity_weight_mean"]
    )
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


CONFIDENCE_EMOJI = {"High": "🟢", "Medium": "🟡", "Low": "🔴"}


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


(
    crime_df,
    boundaries,
    borough_boundaries,
    ward_boundaries,
    weights,
) = load_data()

confidence_by_category = dict(
    zip(weights["major_category"], weights["preventability_confidence"])
)
anchor_by_category = dict(
    zip(weights["major_category"], weights["preventability_anchor"])
)


def format_crime_type(category: str) -> str:
    """Prefix the category name with a confidence dot for the multiselect."""
    confidence = confidence_by_category.get(category, "Low")
    emoji = CONFIDENCE_EMOJI.get(confidence, "⚪")
    return f"{emoji} {category}"

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
        format_func=format_crime_type,
        help="🟢/🟡/🔴 dots indicate evidence strength of the preventability "
             "multiplier (see footer). Empty selection counts as all crime "
             "types."
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
        options=["LSOA", "Ward", "Borough"],
        horizontal=True
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
             "and Composite map modes."
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
    "severity_weighted_mean",
    "severity_weighted_median",
    "preventability_weighted",
    "composite_weighted_mean",
    "composite_weighted_median",
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
elif aggregation_level == "Ward":
    aggregated = (
        filtered
        .dropna(subset=["ward_code"])
        .groupby("ward_code", as_index=False)[METRIC_COLUMNS]
        .sum()
    )
    map_data = ward_boundaries.merge(
        aggregated,
        on="ward_code",
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


basis_suffix = "mean" if severity_basis == "Mean CCHI" else "median"

METRIC_BY_MODE = {
    "Raw crime count": ("crime_count", "Recorded crime count"),
    "Severity-weighted": (
        f"severity_weighted_{basis_suffix}",
        f"Severity-weighted crime count ({severity_basis})"
    ),
    "Preventability-filtered": (
        "preventability_weighted",
        "Preventability-weighted crime count"
    ),
    "Composite (severity x preventability)": (
        f"composite_weighted_{basis_suffix}",
        f"Composite severity × preventability ({severity_basis})"
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
        unsafe_allow_html=True
    )

    visible_categories = (
        selected_crime_types if selected_crime_types else crime_types
    )

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

st.dataframe(
    borough_summary,
    use_container_width=True,
    hide_index=True
)

st.markdown(
    f"**Severity weights** come from the Cambridge Crime Harm Index "
    f"(CCHI) 2020 — currently set to **{severity_basis}** of CCHI scores "
    f"across each category's offences. Toggle the basis in the sidebar. "
    f"Both bases are uniform-weighted across CCHI offence definitions "
    f"(per-offence frequencies aren't published, so the within-category "
    f"offence mix is treated as uniform). CCHI is defined per offence code "
    f"while the dataset stores major-category aggregates, so a single "
    f"category's weight pools offences of different severities — e.g., a "
    f"\"Violence\" weight pools common assault with more serious offences. "
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
