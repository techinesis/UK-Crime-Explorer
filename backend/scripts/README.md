# Backend scripts

One-off / rare ETL and QA scripts. None of these run as part of the live app —
the API reads the **committed** data files they produce. Run them only when the
underlying inputs change, then re-commit the outputs.

Run from `backend/` with the full backend deps (the root `.venv`, which has
geopandas / xgboost), unless a script's own usage note says otherwise.

## `prepare_category_weights.py`

Derives the severity + preventability weights table.

- **Consumes:** the Cambridge Crime Harm Index 2020 scores and the
  literature-anchored preventability table embedded in the script
  (`CCHI_GROUPS_*`, `PREVENTABILITY_*`); auto-detects whether the active raw
  crime CSV uses the legacy 9-category or modern 14-category taxonomy.
- **Produces:** `data/category_weights.csv` (7 columns: `category`,
  `severity_weight_mean`, `severity_weight_median`, `preventability_multiplier`,
  `preventability_tier`, `preventability_confidence`, `preventability_anchor`).
  The tier is derived from the multiplier at write time.
- **Re-run when:** you change the `CCHI_GROUPS_*` / `PREVENTABILITY_*`
  dictionaries. Never hand-edit the CSV — restart the backend afterwards to pick
  up the new weights.

## `forecast_model.py`

Trains the per-tier XGBoost / random-forest forecast models and exports the
dashboard forecast artifacts.

- **Consumes:** the raw monthly crime data (e.g. `.cache/crime-data/london`).
- **Produces:** `forecast_dashboard_long.{csv,json}`, the dashboard prediction
  CSVs, model-evaluation CSVs, `model_metadata.json`, and the per-tier model
  files, into the chosen `--output-dir`.
- **Re-run when:** the forecast needs retraining. Heavy and offline — the
  dashboard never trains; it reads the committed artifacts. Run, then feed the
  output through `prepare_forecast_artifacts.py`.
- **Usage:** `python forecast_model.py --data-dir .cache/crime-data/london --output-dir frontend/public --forecast-months 12`

## `prepare_forecast_artifacts.py`

Compresses the large (gitignored) `forecast_dashboard_long.json` into the two
small gzip files that ARE committed and shipped to production.

- **Consumes:** `forecast_dashboard_long.json` from `forecast_model.py`.
- **Produces:** `data/forecast_dashboard_long.csv.gz` (read by the API
  allocation model) and `frontend/public/forecast_dashboard_long.json.gz`
  (fetched by the SPA in Forecast mode).
- **Re-run when:** `forecast_model.py` regenerates the forecast.
- **Usage (from repo root):** `python backend/scripts/prepare_forecast_artifacts.py`

## `rebuild_boundaries.py`

Regenerates the clean display GeoJSON for all three levels from the source
Ordnance Survey shapefiles.

- **Consumes:** the LSOA / borough / ward shapefiles under `data/*-data/`.
- **Produces:** `data/london_lsoa_boundaries_clean.geojson` (and ward / borough
  equivalents) plus `data/lsoa_to_ward.csv`. Keeps the full generalised vertices
  so adjacent LSOAs share exact edges (no sliver gaps when zoomed).
- **Re-run when:** the boundary source data changes. Needs geopandas.

## `parity_check.py`

QA tool: re-derives the original Streamlit `app.py` map logic inline and diffs it
against the live `/api/map` output, confirming the API reproduces the original
numbers.

- **Consumes:** the running backend (start `uvicorn` on `:8000` first).
- **Produces:** a pass/fail report (no files written).
- **Run when:** verifying a refactor of the composite / map math.

> The runtime crime snapshot (`data/crime_snapshot-london.parquet`) is **not**
> built by a script here — `core.data.load_raw_crime` writes it on first backend
> start (from the cached raw extracts) and it is then committed. Delete it to
> force a rebuild.
