import pandas as pd
import geopandas as gpd
import streamlit as st
import folium
from streamlit_folium import st_folium
import branca.colormap as cm


st.set_page_config(
    page_title="London Crime Explorer",
    page_icon="🕵️",
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
CRIME_PATH = "outputs/crime_aggregated_for_app.csv"

# Approximate London bounding box
LONDON_BOUNDS = [
    [51.28, -0.52],
    [51.70, 0.35]
]


@st.cache_data
def load_data():
    crime_df = pd.read_csv(CRIME_PATH)
    boundaries = gpd.read_file(BOUNDARIES_PATH)

    crime_df["lsoa_code"] = crime_df["lsoa_code"].astype(str)
    boundaries["lsoa_code"] = boundaries["lsoa_code"].astype(str)

    return crime_df, boundaries


def create_map(map_data, selected_metric, selected_borough):
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

    if selected_metric == "crime_share":
        colormap.caption = "Crime share within selected data (%)"
    else:
        colormap.caption = "Recorded crime count"

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

    tooltip = folium.GeoJsonTooltip(
        fields=[
            "lsoa_name",
            "borough",
            "crime_count",
            selected_metric
        ],
        aliases=[
            "LSOA:",
            "Borough:",
            "Crime count:",
            "Displayed value:"
        ],
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


crime_df, boundaries = load_data()


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

    selected_crime_type = st.selectbox(
        "Crime type",
        options=["All crime types"] + crime_types
    )

    years = sorted(crime_df["year"].dropna().unique())

    selected_year = st.selectbox(
        "Year",
        options=["All years"] + years
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

    classification_mode = st.radio(
        "Map mode",
        options=[
            "Raw crime count",
            "Crime share within selected data"
        ]
    )


# -----------------------------
# Filtering
# -----------------------------

filtered = crime_df.copy()

if selected_crime_type != "All crime types":
    filtered = filtered[filtered["major_category"] == selected_crime_type]

if selected_year != "All years":
    filtered = filtered[filtered["year"] == selected_year]

if selected_months:
    filtered = filtered[filtered["month"].isin(selected_months)]

if selected_borough != "All boroughs":
    filtered = filtered[filtered["borough"] == selected_borough]


crime_by_lsoa = (
    filtered
    .groupby("lsoa_code", as_index=False)["crime_count"]
    .sum()
)

map_data = boundaries.merge(
    crime_by_lsoa,
    on="lsoa_code",
    how="left"
)

map_data["crime_count"] = map_data["crime_count"].fillna(0)

if classification_mode == "Crime share within selected data":
    total_selected_crime = map_data["crime_count"].sum()

    if total_selected_crime > 0:
        map_data["crime_share"] = (
            map_data["crime_count"] / total_selected_crime
        ) * 100
    else:
        map_data["crime_share"] = 0

    selected_metric = "crime_share"
else:
    selected_metric = "crime_count"


# -----------------------------
# Summary values
# -----------------------------

total_crimes = int(map_data["crime_count"].sum())
active_lsoas = int((map_data["crime_count"] > 0).sum())
average_per_lsoa = round(map_data["crime_count"].mean(), 2)

top_lsoas = (
    map_data[
        ["lsoa_code", "lsoa_name", "borough", "crime_count"]
    ]
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
    st.metric("LSOAs with crimes", f"{active_lsoas:,}")

with metric_col_3:
    st.metric("Average per LSOA", f"{average_per_lsoa:,}")


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
        selected_borough=selected_borough
    )

    st_folium(
        crime_map,
        use_container_width=True,
        height=720,
        returned_objects=[]
    )


with right_col:
    st.markdown(
        """
        <div class="panel">
            <div class="section-title">Top 10 LSOAs</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.dataframe(
        top_lsoas,
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

    st.write(f"**Crime type:** {selected_crime_type}")
    st.write(f"**Year:** {selected_year}")
    st.write(f"**Borough:** {selected_borough}")
    st.write(f"**Months selected:** {len(selected_months)}")


st.markdown("---")

st.markdown("### Borough summary")

st.dataframe(
    borough_summary,
    use_container_width=True,
    hide_index=True
)