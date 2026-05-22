# London Crime Explorer

An interactive web app that maps recorded crime across London and exposes a
composite **police-demand signal** (`crime count × severity × preventability`)
at LSOA, ward, and borough level.

- **Severity** comes from the **Cambridge Crime Harm Index 2020** (recommended
  sentence in days), exposed on a Mean / Median basis.
- **Preventability** multipliers are anchored in the hot-spot policing
  literature, each with a confidence rating and a one-line citation.

Built for **TU/e 4CBLW020 — Multidisciplinary Challenge-Based Learning,
Group 3**.

The app is a conventional full-stack web app:

- **Backend** — FastAPI serving the analysis as a small JSON API. The
  framework-agnostic analysis lives in `backend/core/` (data loading,
  filtering, aggregation, the composite metric) so it can be reused directly
  by other workstreams.
- **Frontend** — Vite + React + TypeScript. The choropleth is rendered with
  **deck.gl** over a token-free **MapLibre** (CARTO) basemap; server state is
  managed with TanStack Query.

---

## Features

Sidebar controls:

- **Map mode**: Raw crime count · Crime share within selection · Severity-weighted ·
  Preventability-filtered · Composite (severity × preventability).
- **Severity basis**: Mean CCHI / Median CCHI (changes the severity and
  composite modes).
- **Aggregation level**: LSOA · Ward · Borough.
- **Crime type** multi-select with a confidence prefix (🟢 High / 🟡 Medium /
  🔴 Low). An empty selection counts as all types.
- **Preventability tier**, **year**, **months**, and **borough** filters.

Map and panels:

- A YlOrRd choropleth with a legend (min/max for the active metric) and
  hover tooltips (unit name, borough, crime count, displayed value).
- Selecting a borough refits the view to it.
- **Top 10** units by the active metric, a **current-selection** recap, a
  **borough summary** table, and a **sources** panel listing the confidence and
  literature anchor for each selected category.
- A **time animation** that steps through every `(year, month)` period present
  in the data, with play / pause / reset and a scrubber.

---

## Prerequisites

- **Python 3.12** (the geospatial stack pins `numpy==1.26.4`, which has no
  prebuilt wheel for 3.14).
- **Node.js 20+** and npm.

The boundary GeoJSONs, the CCHI spreadsheet, `category_weights.csv`, and a
compressed seed of the crime data are committed under `data/`, so a fresh
clone can run without any extra downloads.

---

## Setup

### Backend

```powershell
cd backend
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1            # Windows PowerShell
# source .venv/bin/activate           # macOS / Linux
pip install -r requirements.txt
```

### Frontend

```powershell
cd frontend
npm install
```

---

## Running

Run the two servers in separate terminals.

**Backend** (serves the API at `http://127.0.0.1:8000`):

```powershell
cd backend
uvicorn api.main:app --reload
```

The first start assembles the crime dataset and writes a parquet snapshot
(`data/crime_snapshot.parquet`); later starts read the snapshot and are
near-instant. To rebuild it, delete that file.

**Frontend** (serves the app at `http://localhost:5173`):

```powershell
cd frontend
npm run dev
```

The dev server proxies `/api` to the backend, so open
`http://localhost:5173` and the app talks to FastAPI with no extra config.

---

## API

All routes are under `/api`:

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/meta` | Years, months, periods, categories (+ metadata), boroughs, tiers |
| POST | `/api/map` | Per-unit values + crime counts + colour-scale bounds for a filter set |
| GET | `/api/weights` | The full category weights table |

Interactive API docs are available at `http://127.0.0.1:8000/docs`.

Boundary GeoJSON is **not** an API route — it is served as static assets at
`/boundaries/{level}.json`, pre-baked by `frontend/scripts/prepare-static.mjs`
(run automatically before `dev` and `build`).

---

## Deploying to Vercel

The app deploys as a static frontend (CDN) plus one lightweight Python
serverless function:

- `frontend/dist` → static site, including the pre-baked `/boundaries/*.json`.
- `api/index.py` → FastAPI function for `/api/meta`, `/api/map`, `/api/weights`.
  It reads the committed `data/crime_snapshot.parquet` (~2 MB) and uses **pandas
  only** — no geopandas — so the bundle is small and cold starts are fast.

`vercel.json` wires it up (frontend build command, `/api/*` rewrite to the
function, and the data files the function needs). No environment variables or
API keys are required (the basemap is token-free).

To deploy: import the repository at [vercel.com/new](https://vercel.com/new),
keep the **root directory at the repository root** (not `frontend/`), and deploy.
Vercel reads `vercel.json` automatically. Pushes to a branch get a preview URL;
the production branch deploys on merge.

---

## Project layout

```
backend/
  core/        framework-agnostic analysis (no web deps)
    data.py        load / filter / aggregate the crime data
    weights.py     severity + preventability lookup
    composite.py   the five metric columns + metric resolution
    geometry.py    boundary GeoJSON loading
    paths.py       data/cache path resolution
  api/
    client.py      data.police.uk + Kaggle fetcher
    main.py        FastAPI app + routes
    schemas.py     Pydantic request/response models
  scripts/     ETL: boundary preparation + weight derivation
  tests/       pytest unit + API tests
  requirements.txt
frontend/
  src/
    components/  CrimeMap, Sidebar, Legend, AnimationControls, panels
    hooks/       useFilters, useCrimeData, useAnimation
    lib/         api (typed fetch), types (mirror schemas), colors (YlOrRd)
data/          boundaries, weights, CCHI source, crime seed (committed)
```

---

## Tests

```powershell
cd backend
.venv\Scripts\Activate.ps1
pytest
```

Covers the composite math, metric resolution, filtering/aggregation, and the
API endpoints against the loaded data.

---

## Re-deriving severity / preventability weights

`data/category_weights.csv` is read at startup and has seven columns:
`category, severity_weight_mean, severity_weight_median,
preventability_multiplier, preventability_tier, preventability_confidence,
preventability_anchor`.

Do not hand-edit it. Change the source-of-truth dictionaries in
`backend/scripts/prepare_category_weights.py` (`CCHI_GROUPS_*` and
`PREVENTABILITY_*`) and re-run it; the preventability tier is derived from the
multiplier automatically. Restart the backend afterwards to pick up the change.

---

## Data sources

- **Crime counts** — *London Crime Data, 2008–2016* (Kaggle `jboysen/london-crime`)
  combined with recent monthly extracts from data.police.uk, aggregated to
  LSOA × month × category.
- **Boundaries** — Greater London Authority statistical GIS files (LSOA 2011,
  generalised), reprojected to EPSG:4326 and simplified for the web.
- **Severity** — *Cambridge Crime Harm Index 2020 Update* (Cambridge Centre for
  Evidence-Based Policing).
- **Preventability** — anchored in Braga et al. (2019), Weisburd (2015, 2021),
  and Sherman, Neyroud & Neyroud (2016).
