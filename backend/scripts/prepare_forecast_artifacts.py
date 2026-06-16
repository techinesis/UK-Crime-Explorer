"""Build the committed, compressed forecast artifacts from the model's long table.

Reads the large (gitignored) ``forecast_dashboard_long.json`` and writes two small
gzipped files that ARE committed and shipped to production:

  - ``data/forecast_dashboard_long.csv.gz``
        Read by the API allocation model (``core.data.get_forecast_long``). Lives under
        ``data/`` so it ships into the Vercel function via ``includeFiles``; pandas
        decompresses ``.gz`` transparently.

  - ``frontend/public/forecast_dashboard_long.json.gz``
        Expanded at build time by ``frontend/scripts/prepare-forecast.mjs`` and fetched
        by the SPA in Forecast mode (``hooks/useCrimeData.ts``).

The frontend copy keeps only the columns the parser reads — ``Month``, ``LSOA code``,
``Crime type``, ``predicted_crimes`` — dropping ``actual_crimes`` (always null) and
``prediction_type`` (constant) to trim the served JSON by ~30%. The backend CSV keeps
every column for fidelity (the allocation model reads only three of them; gzip flattens
the rest).

This is a rare ETL step — re-run it whenever ``forecast_model.py`` regenerates the
forecast. Run from the repo root with the full backend deps (the root ``.venv``):

    python backend/scripts/prepare_forecast_artifacts.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

# backend/scripts/prepare_forecast_artifacts.py -> parents[2] = repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SRC = REPO_ROOT / "frontend" / "public" / "forecast_dashboard_long.json"
DEFAULT_CSV_GZ = REPO_ROOT / "data" / "forecast_dashboard_long.csv.gz"
DEFAULT_JSON_GZ = REPO_ROOT / "frontend" / "public" / "forecast_dashboard_long.json.gz"

# Columns the frontend parser (hooks/useCrimeData.ts) actually reads.
FRONTEND_COLUMNS = ["Month", "LSOA code", "Crime type", "predicted_crimes"]


def _mb(path: Path) -> float:
    return path.stat().st_size / 1e6


def main() -> None:
    parser = argparse.ArgumentParser(description="Build compressed forecast artifacts.")
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC,
                        help="source forecast_dashboard_long.json (the large file)")
    parser.add_argument("--csv-gz", type=Path, default=DEFAULT_CSV_GZ,
                        help="output backend CSV (gzipped)")
    parser.add_argument("--json-gz", type=Path, default=DEFAULT_JSON_GZ,
                        help="output frontend JSON (gzipped, slim)")
    args = parser.parse_args()

    if not args.src.exists():
        raise SystemExit(f"source forecast JSON not found: {args.src}")

    print(f"reading {args.src.name} ({_mb(args.src):.0f} MB)...")
    # convert_dates=False keeps "Month" (e.g. "2026-04") as a plain string.
    df = pd.read_json(args.src, convert_dates=False)
    print(f"  {len(df):,} rows, columns: {list(df.columns)}")

    args.csv_gz.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.csv_gz, index=False, compression="gzip")
    print(f"wrote {args.csv_gz.name} ({_mb(args.csv_gz):.1f} MB) — backend allocation CSV")

    missing = [c for c in FRONTEND_COLUMNS if c not in df.columns]
    if missing:
        raise SystemExit(f"source is missing frontend columns: {missing}")
    slim = df[FRONTEND_COLUMNS]
    slim.to_json(args.json_gz, orient="records", compression="gzip")
    print(f"wrote {args.json_gz.name} ({_mb(args.json_gz):.1f} MB) — frontend forecast JSON")


if __name__ == "__main__":
    main()
