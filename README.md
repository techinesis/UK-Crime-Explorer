# London Crime Explorer

Streamlit dashboard for exploring recorded crime across London at the **LSOA**
(Lower Super Output Area) level, with severity weighting from the **Cambridge
Crime Harm Index** and a first-pass preventability mapping for visible-patrol
deployment analysis.

Built for **TU/e 4CBLW020 — Multidisciplinary Challenge-Based Learning, Group 3**.

---

## Features

Sidebar filters:

- **Multi-select crime type** with a confidence emoji prefix (🟢 High / 🟡 Medium / 🔴 Low) reflecting evidence strength of each category's preventability multiplier. Categories flagged 🔴 should be interpreted with care.
- **Preventability tier** filter (`All` / `High` / `Medium` / `Low`).
- **Borough** drilldown.
- **Year + month** filters, **or** an animated time slider that steps through every month in the dataset (Jan 2008 – Dec 2016) with Play / Pause / Reset.
- **Aggregation level** toggle: **LSOA** (≈4,800 polygons), **Ward** (≈625), or **Borough** (33). Ward and borough aggregations sum the underlying LSOA crime counts.
- **Severity basis** radio (`Mean CCHI` / `Median CCHI`, default Mean). CCHI offences vary widely in severity inside a category — Mean preserves total harm-days, Median is robust to long-tailed offence mixes. The toggle changes both Severity-weighted and Composite map modes.

Map modes (each rescales the choropleth):

- **Raw crime count** — recorded crimes in the current selection.
- **Crime share within selected data** — percent of the filtered total.
- **Severity-weighted** — `crime_count × CCHI score (mean or median)`. Values are approximate harm-days (CCHI uses days of recommended sentence as the unit).
- **Preventability-filtered** — `crime_count × preventability_multiplier`.
- **Composite** — severity × preventability together. The headline demand signal for patrol-allocation analysis.

Side panels:

- **Top 10 LSOAs / boroughs** (depends on aggregation level).
- **Current selection** recap so you can sanity-check the filters (now also shows the active severity basis).
- **Selected category sources** — confidence rating + one-line literature anchor per selected crime type, so you can defend any number on the map.
- **Borough summary** table at the bottom.

---

## Prerequisites

- **Python 3.12.** Do **not** use 3.14 — `numpy==1.26.4` (pinned for the
  geopandas/pandas combo this project uses) has no prebuilt wheel for 3.14
  and pip will fail to compile it from source on Windows.

Everything else (the LSOA and borough shapefiles, the CCHI 2020 spreadsheet,
`data/category_weights.csv`, and the cleaned boundary GeoJSONs) is already in the
repo.

---

## Setup

```powershell
# 1. Clone (skip if you already have the repo)
git clone https://github.com/dragos6523/4CBLW020-Group-3.git
cd 4CBLW020-Group-3

# 2. Create and activate a Python 3.12 virtual environment
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1            # Windows PowerShell
# source .venv/bin/activate           # macOS / Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. (Optional) Re-derive severity weights from the CCHI 2020 spreadsheet
python prepare_category_weights.py        # already run; commit ships the output
```

If `Activate.ps1` is blocked by PowerShell's execution policy, run this once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

---

## Running the dashboard

```powershell
streamlit run app.py
```

Streamlit will open `http://localhost:8501` in your browser. The first load
takes a bit longer as the API module may need to fetch extra data or grab the
Kaggle dataset if you do not have it yet. After that, repeat filter combinations
are near-instant; fresh combinations take a few hundred milliseconds.

To stop the server, press `Ctrl+C` in the terminal.

---

## Re-deriving severity / preventability weights

`data/category_weights.csv` is committed and the dashboard reads it at startup.
It always has **7 columns**:

```
major_category,
severity_weight_mean, severity_weight_median,
preventability_multiplier, preventability_tier,
preventability_confidence, preventability_anchor
```

`scripts/prepare_category_weights.py` is **hybrid** — it auto-detects whether the
active `.cache/crime-data/london_crime_by_lsoa.csv` uses the legacy 9-category MPS taxonomy
or the modern 14-category data.police.uk taxonomy and emits a matching CSV
(9 rows or 14 rows) with the same column schema either way.

**Do not hand-edit the CSV** — change the source-of-truth dictionaries in
`scripts/prepare_category_weights.py`:

- `CCHI_GROUPS_9` / `CCHI_GROUPS_14` — which CCHI 2020 `GROUP` value(s) feed
  each `major_category` label in each schema. The script computes both the
  **mean** and the **median** CCHI score across matched offences (uniform
  weights — CCHI doesn't publish per-offence frequencies).
- `PREVENTABILITY_9` / `PREVENTABILITY_14` — `(multiplier, confidence, anchor)`
  per category. The tier (`High` / `Medium` / `Low`) is **derived from the
  multiplier at write time**, so changing a multiplier auto-updates the tier.
  Anchors are one-line literature citations (Braga 2019, Weisburd 2015,
  Sherman/Neyroud 2016, etc.) shown in the dashboard's *Selected category
  sources* panel.

Then re-run:

```powershell
python prepare_category_weights.py
```

Restart Streamlit afterwards (or bump `LOAD_DATA_CACHE_VERSION` in `app.py`)
to clear the `@st.cache_data` cache.

---

## Repository layout

```
4CBLW020-Group-3/
├── app.py                          # Streamlit dashboard (the main entry point)
├── requirements.txt
├── .streamlit/config.toml          # Dark theme + enableStaticServing for URL-based geometry
├── static/colored/                 # Runtime cache of colored GeoJSON files (gitignored)
├── scripts/
│   ├── prepare_interactive_data.py # ETL: shapefiles → data/
│   └── prepare_category_weights.py # Derives data/category_weights.csv from CCHI
├── .cache/                         # Application data cache
└── data/
    ├── london_lsoa_boundaries_clean.geojson      # Committed (~4 MB)
    ├── london_borough_boundaries_clean.geojson   # Committed (~150 KB)
    ├── london_ward_boundaries_clean.geojson      # Committed (~750 KB)
    ├── lsoa_to_ward.csv                          # Committed; LSOA → ward map
    ├── cchi2020dataxls.xlsx        # CCHI 2020 update (committed)
    ├── category_weights.csv        # Derived severity + preventability lookup (committed)
    └── statistical-gis-boundaries-london/
        └── ESRI/                   # LSOA, ward, and borough shapefiles (committed)
```

---

## Data sources

- **Crime counts.** *London Crime Data, 2008–2016* (Kaggle dataset
  `jboysen/london-crime`), originally derived from
  data.police.uk public archives. Aggregated to LSOA × month × major category.
- **LSOA / borough / ward boundaries.** Greater London Authority statistical
  GIS boundary files (LSOA 2011, generalised, MHW excluded). Reprojected from
  British National Grid to **EPSG:4326** (WGS84) and simplified with
  `tolerance=0.0005` for browser-friendly rendering.
- **Severity weights.** *Cambridge Crime Harm Index 2020 Update*, produced by
  the Cambridge Centre for Evidence-Based Policing. Each offence's CCHI score
  is the recommended starting-point sentence in days, per the England and
  Wales sentencing guidelines current as of 2020-10-06. The dashboard exposes
  both the mean and the median CCHI score per category and lets you toggle
  which one is used at display time.
- **Preventability multipliers.** Anchored in the literature: Braga, Turchan,
  Papachristos & Hureau (2019) Campbell SR meta-analysis of hot-spot policing
  (disorder ES = 0.161, drug crime ES = 0.244, violent crime ES = 0.102);
  Weisburd (2015) on crime concentration in micro-places (e.g., 100% of
  robberies recorded in 2.2% of places); Weisburd (2021) MIT Press review of
  presence vs response; Sherman, Neyroud & Neyroud (2016) for CCHI
  methodology. Each row's one-line citation lives in
  `data/category_weights.csv:preventability_anchor` and is surfaced in the
  *Selected category sources* panel.

---

## Known limitations & gotchas

- **Major-category granularity.** The 2008–2016 Met dataset uses 9 major
  categories (older taxonomy); the modern data.police.uk schema has 14.
  `prepare_category_weights.py` is hybrid — drop in a 14-category CSV at
  `data/london_crime_by_lsoa.csv` and re-run, no other code changes needed.
  CCHI is defined per offence code, so every category-level severity weight
  averages over a heterogeneous mix (`Violence Against the Person` lumps
  common assault with murder; mean = 808 days, median = 19 days). The
  sidebar `Severity basis` toggle (Mean / Median) lets you flip between
  total-harm conservation (Mean) and a typical-offence view (Median); they
  produce visibly different rankings, so always state the basis you used
  when sharing screenshots.
- **Anti-social behaviour has no CCHI severity.** ASB is non-notifiable and
  outside CCHI's scope. In the 14-schema, the `Anti-social behaviour` row
  has `NaN` severity (the app coerces it to 0 in severity-weighted modes
  but keeps the category visible in raw-count and preventability modes).
- **Day-of-week and sub-monthly patterns** are not recoverable — they were
  anonymised at source by data.police.uk before the dataset was published.
- **Animation frame rate** with the default pydeck engine is GPU-bound and
  hits 30+ fps even in LSOA mode (4,879 polygons). If you flip the sidebar
  "New map engine (beta)" toggle off, the Folium fallback runs at ~0.5 fps
  in LSOA mode and is noticeably faster in Borough mode (33 polygons).
- **Port 8501 zombies.** On Windows, killing a Streamlit shell wrapper does
  not always propagate to the underlying Python process. If a restart seems
  to ignore your changes, run `netstat -ano | findstr :8501` and
  `Stop-Process -Id <pid> -Force` on any orphaned PID before starting again.
- **OneDrive sync.** If your clone lives under a OneDrive folder, the first
  ETL run can be slow because the shapefile is fetched on demand (Files
  On-Demand). Subsequent runs are fast.

---

## License & attribution

Boundary data ships under the GLA's standard licence terms (see
`data/statistical-gis-boundaries-london/Geography-licensing.pdf`). The CCHI
2020 spreadsheet is redistributed for academic use under the terms set by
the Cambridge Centre for Evidence-Based Policing. Crime data is public via
data.police.uk.
