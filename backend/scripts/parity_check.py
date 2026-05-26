"""Numerical parity check: independent reimplementation of the Streamlit
app.py display logic vs the live FastAPI /api/map output.

Run the backend first (uvicorn on :8000), then:  python scripts/parity_check.py

This deliberately re-derives compute_map_data + METRIC_BY_MODE + the share and
vmin/vmax conventions from app.py inline (a separate code path from core/), so a
match confirms the API faithfully reproduces the original behaviour.
"""

from __future__ import annotations

import sys

import requests

from core.data import get_crime_long
from core.geometry import unit_ids

API = "http://127.0.0.1:8000"
TOL = 1e-6

METRIC_COLUMNS = [
    "crime_count",
    "severity_weighted_mean",
    "severity_weighted_median",
    "preventability_weighted",
    "composite_weighted_mean",
    "composite_weighted_median",
]

# new metric enum -> app.py mode string
MODE_BY_METRIC = {
    "raw": "Raw crime count",
    "share": "Crime share within selected data",
    "severity": "Severity-weighted",
    "preventability": "Preventability-filtered",
    "composite": "Composite (severity x preventability)",
}
ID_COL = {"lsoa": "lsoa_code", "ward": "ward_code", "borough": "borough"}


def app_filter(df, categories, tier, year, months, borough):
    """app.py:424-439."""
    f = df
    if categories:
        f = f[f["category"].isin(list(categories))]
    if tier != "All tiers":
        f = f[f["preventability_tier"] == tier]
    if year != "All years":
        f = f[f["year"] == year]
    if months:
        f = f[f["month"].isin(list(months))]
    if borough != "All boroughs":
        f = f[f["borough"] == borough]
    return f


def app_values(df, categories, tier, year, months, borough, level, metric, basis_label):
    """Reproduce the per-unit value dict + vmin/vmax exactly as app.py would."""
    id_col = ID_COL[level]
    f = app_filter(df, categories, tier, year, months, borough)
    if level == "ward":
        f = f.dropna(subset=["ward_code"])
    agg = f.groupby(id_col, as_index=False, observed=True)[METRIC_COLUMNS].sum()

    # boundary left-join => every unit present, 0-filled (app.py:441-469)
    agg[id_col] = agg[id_col].astype(str)
    agg = agg.set_index(id_col).reindex([str(i) for i in unit_ids(level)]).fillna(0.0)

    suffix = "mean" if basis_label == "Mean CCHI" else "median"
    mode = MODE_BY_METRIC[metric]
    if mode == "Crime share within selected data":
        total = agg["crime_count"].sum()
        series = (agg["crime_count"] / total * 100) if total > 0 else agg["crime_count"] * 0
    else:
        col = {
            "Raw crime count": "crime_count",
            "Severity-weighted": f"severity_weighted_{suffix}",
            "Preventability-filtered": "preventability_weighted",
            "Composite (severity x preventability)": f"composite_weighted_{suffix}",
        }[mode]
        series = agg[col]

    series = series.fillna(0.0).astype(float)
    vmin = float(series.min())
    vmax = max(float(series.max()), 1.0)
    return {str(k): float(v) for k, v in series.items()}, vmin, vmax


def main() -> int:
    df = get_crime_long()

    filtersets = [
        dict(categories=(), tier="All tiers", year="All years", months=(), borough="All boroughs"),
        dict(categories=(), tier="All tiers", year="All years", months=(), borough="Westminster"),
        dict(categories=("Burglary",), tier="All tiers", year="All years", months=(), borough="All boroughs"),
        dict(categories=("Burglary", "Drugs"), tier="High", year=2024, months=(1, 2, 3), borough="All boroughs"),
        dict(categories=(), tier="Medium", year=2015, months=(6,), borough="Camden"),
    ]
    levels = ["lsoa", "ward", "borough"]
    metrics = ["raw", "share", "severity", "preventability", "composite"]
    bases = [("mean", "Mean CCHI"), ("median", "Median CCHI")]

    checks = 0
    worst = 0.0
    failures = []

    for fs in filtersets:
        for level in levels:
            for metric in metrics:
                for basis_api, basis_label in bases:
                    if metric not in ("severity", "composite") and basis_api == "median":
                        continue  # basis only matters for severity/composite

                    exp_vals, exp_vmin, exp_vmax = app_values(
                        df, fs["categories"], fs["tier"], fs["year"], fs["months"],
                        fs["borough"], level, metric, basis_label,
                    )

                    year = None if fs["year"] == "All years" else fs["year"]
                    body = {
                        "categories": list(fs["categories"]),
                        "tier": fs["tier"],
                        "year": year,
                        "months": list(fs["months"]),
                        "borough": fs["borough"],
                        "level": level,
                        "metric": metric,
                        "severity_basis": basis_api,
                    }
                    r = requests.post(f"{API}/api/map", json=body, timeout=60)
                    r.raise_for_status()
                    got = r.json()

                    checks += 1
                    if set(got["values"]) != set(exp_vals):
                        failures.append(f"id mismatch {level}/{metric} fs={fs}")
                        continue
                    dmax = max(abs(got["values"][k] - exp_vals[k]) for k in exp_vals)
                    dmax = max(dmax, abs(got["vmin"] - exp_vmin), abs(got["vmax"] - exp_vmax))
                    worst = max(worst, dmax)
                    if dmax > TOL:
                        failures.append(
                            f"value mismatch {level}/{metric}/{basis_api} fs={fs} maxdiff={dmax:.6g}"
                        )

    print(f"combinations checked: {checks}")
    print(f"worst absolute difference: {worst:.3e}")
    if failures:
        print(f"FAILURES ({len(failures)}):")
        for f in failures[:20]:
            print("  -", f)
        return 1
    print("PARITY OK — every combination matches the app.py reimplementation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
