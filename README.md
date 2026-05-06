# London Crime Explorer

Streamlit dashboard for exploring recorded crime across London at the **LSOA**
(Lower Super Output Area) level, with severity weighting from the **Cambridge
Crime Harm Index** and a first-pass preventability mapping for visible-patrol
deployment analysis.

Built for **TU/e 4CBLW020 — Multidisciplinary Challenge-Based Learning, Group 3**.

---

## Features

Sidebar filters:

- Multi-select crime type (defaults to all 9 Met categories present in the data).
- Preventability tier filter (`All` / `High` / `Medium` / `Low`).
- Borough drilldown.
- Year + month filters, **or** an animated time slider that steps through every
  month in the dataset (Jan 2008 – Dec 2016) with Play / Pause / Reset.
- Aggregation level toggle: **LSOA** (≈4,800 polygons), **Ward** (≈625), or **Borough** (33). Ward and borough aggregations sum the underlying LSOA crime counts.

Map modes (each rescales the choropleth):

- **Raw crime count** — recorded crimes in the current selection.
- **Crime share within selected data** — percent of the filtered total.
- **Severity-weighted** — `crime_count × CCHI score`. Values are approximate
  harm-days (CCHI uses days of recommended sentence as the unit).
- **Preventability-filtered** — `crime_count × preventability_multiplier`.
- **Composite** — severity × preventability together. The headline demand
  signal for patrol-allocation analysis.

Side panels:

- Top 10 LSOAs / boroughs (depends on aggregation level).
- Current-selection recap so you can sanity-check the filters.
- Borough summary table at the bottom.

---

## Prerequisites

- **Python 3.12.** Do **not** use 3.14 — `numpy==1.26.4` (pinned for the
  geopandas/pandas combo this project uses) has no prebuilt wheel for 3.14
  and pip will fail to compile it from source on Windows.
- **The raw Kaggle CSV** — `london_crime_by_lsoa.csv` from the public dataset
  *London Crime Data, 2008–2016* (`jboysen/london-crime` on Kaggle). It is
  gitignored because of size, so a fresh clone does **not** include it.
  Download it manually and drop it at `data/london_crime_by_lsoa.csv`.

Everything else (the LSOA and borough shapefiles, the CCHI 2020 spreadsheet,
`category_weights.csv`, and the cleaned boundary GeoJSONs) is already in the
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

# 4. Place the raw Kaggle CSV at data/london_crime_by_lsoa.csv
#    (Download from https://www.kaggle.com/datasets/jboysen/london-crime)

# 5. One-time ETL: build the aggregated crime CSV and the cleaned boundary GeoJSONs
python prepare_interactive_data.py        # ~1–3 minutes; prints "ok" when done

# 6. (Optional) Re-derive severity weights from the CCHI 2020 spreadsheet
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
takes ~10–15 seconds because `load_data()` reads the 6.4M-row aggregated CSV
and both boundary GeoJSONs. After that, filter changes are near-instant.

To stop the server, press `Ctrl+C` in the terminal.

---

## Re-deriving severity / preventability weights

`data/category_weights.csv` is committed and the dashboard reads it at startup.
**Do not hand-edit the CSV** — change the source-of-truth dictionaries in
`prepare_category_weights.py`:

- `CATEGORY_TO_CCHI_GROUPS` — which CCHI 2020 `GROUP` value(s) feed each of the
  9 user `major_category` labels. Severity is the **offence-count-weighted
  mean CCHI score** across all matched offences (in days of recommended
  sentence, per CCHI's definition).
- `PREVENTABILITY_DEFAULTS` — `(tier, multiplier)` per major_category. These
  are placeholder values from the project's first-pass mapping. Sub-question 4
  will replace them once finalized.

Then re-run:

```powershell
python prepare_category_weights.py
```

Restart Streamlit afterwards to clear the `@st.cache_data` cache.

---

## Repository layout

```
4CBLW020-Group-3/
├── app.py                          # Streamlit dashboard (the main entry point)
├── prepare_interactive_data.py     # ETL: shapefiles + raw CSV → outputs/
├── prepare_category_weights.py     # Derives data/category_weights.csv from CCHI
├── requirements.txt
├── CLAUDE.md                       # Architecture notes for AI-assisted dev
├── data/
│   ├── london_crime_by_lsoa.csv    # Raw Met Police data (gitignored — fetch from Kaggle)
│   ├── cchi2020dataxls.xlsx        # CCHI 2020 update (committed)
│   ├── category_weights.csv        # Derived severity + preventability lookup (committed)
│   └── statistical-gis-boundaries-london/
│       └── ESRI/                   # LSOA, ward, and borough shapefiles (committed)
└── outputs/
    ├── london_lsoa_boundaries_clean.geojson      # Committed (~4 MB)
    ├── london_borough_boundaries_clean.geojson   # Committed (~150 KB)
    ├── london_ward_boundaries_clean.geojson      # Committed (~750 KB)
    ├── lsoa_to_ward.csv                          # Committed; LSOA → ward map
    └── crime_aggregated_for_app.csv              # Gitignored — regenerate via ETL
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
  Wales sentencing guidelines current as of 2020-10-06.
- **Preventability tiers.** Project first-pass mapping (Robbery → high;
  Burglary, Theft → medium; everything else → low). Will be replaced by the
  formal categorisation from research sub-question 4.

---

## Known limitations & gotchas

- **Major-category granularity.** The 2008–2016 Met dataset uses 9
  major categories (older taxonomy). CCHI is defined per offence code, so
  every category-level severity weight averages over a heterogeneous mix
  (`Violence Against the Person` lumps common assault with murder; mean = 808
  days, median = 19 days). The dashboard currently uses the mean for
  total-harm conservation; the right summary statistic is an open question.
- **Day-of-week and sub-monthly patterns** are not recoverable — they were
  anonymised at source by data.police.uk before the dataset was published.
- **Animation frame rate** is bounded by Folium's render time on the
  ~5,000-LSOA choropleth (~0.5 fps in LSOA mode). It is noticeably faster in
  Borough mode (33 polygons).
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
