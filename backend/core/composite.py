"""The demand-signal metric columns and the single metric-resolution point.

Pure functions over a pandas DataFrame — no web or geospatial dependencies —
so the composite math can be unit-tested in isolation. The formulas mirror
``load_data()`` in the original Streamlit ``app.py`` exactly; nothing about the
numbers changes in the rewrite.
"""

from __future__ import annotations

import pandas as pd

# The six summable metric columns carried on the long crime DataFrame. Group-by
# aggregation sums each of these, so every map mode resolves to one of them
# (or, for "share", is derived from crime_count post-aggregation).
METRIC_COLUMNS: tuple[str, ...] = (
    "crime_count",
    "severity_weighted_mean",
    "severity_weighted_median",
    "preventability_weighted",
    "composite_weighted_mean",
    "composite_weighted_median",
)

# The five public map modes. "share" is special — it is a percentage of the
# filtered total computed after aggregation, not a precomputed column.
VALID_METRICS: tuple[str, ...] = ("raw", "share", "severity", "preventability", "composite")
VALID_SEVERITY_BASES: tuple[str, ...] = ("mean", "median")


def add_composite_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of ``df`` with the five weighted metric columns added.

    Requires ``crime_count``, ``severity_weight_mean``, ``severity_weight_median``
    and ``preventability_multiplier`` columns. NaN severities (e.g. Anti-social
    behaviour, which is outside CCHI's scope) must already be coerced to 0 by
    the caller; preventability is retained for those rows.
    """
    out = df.copy()
    out["severity_weighted_mean"] = out["crime_count"] * out["severity_weight_mean"]
    out["severity_weighted_median"] = out["crime_count"] * out["severity_weight_median"]
    out["preventability_weighted"] = out["crime_count"] * out["preventability_multiplier"]
    out["composite_weighted_mean"] = (
        out["crime_count"] * out["severity_weight_mean"] * out["preventability_multiplier"]
    )
    out["composite_weighted_median"] = (
        out["crime_count"] * out["severity_weight_median"] * out["preventability_multiplier"]
    )
    return out


def resolve_metric(metric: str, severity_basis: str) -> str:
    """Map a public ``metric`` + ``severity_basis`` to a METRIC_COLUMNS name.

    "share" resolves to ``crime_count`` here; the percentage transform happens
    in :func:`compute_map_values`. This is the ONE place mode→column lives.
    """
    if metric not in VALID_METRICS:
        raise ValueError(f"unknown metric {metric!r}; expected one of {VALID_METRICS}")
    if severity_basis not in VALID_SEVERITY_BASES:
        raise ValueError(
            f"unknown severity_basis {severity_basis!r}; expected one of {VALID_SEVERITY_BASES}"
        )
    suffix = severity_basis  # "mean" | "median"
    return {
        "raw": "crime_count",
        "share": "crime_count",
        "severity": f"severity_weighted_{suffix}",
        "preventability": "preventability_weighted",
        "composite": f"composite_weighted_{suffix}",
    }[metric]


def compute_map_values(
    aggregated: pd.DataFrame,
    metric: str,
    severity_basis: str,
) -> tuple[pd.Series, float, float]:
    """Resolve the displayed per-unit value series plus its colour-scale bounds.

    ``aggregated`` is the per-unit frame (one row per map unit, every
    METRIC_COLUMNS column present and 0-filled). Returns ``(values, vmin, vmax)``
    where ``vmax`` is floored to 1.0 so a uniformly-zero selection still yields a
    valid YlOrRd normalisation — matching ``prepare_colored_layer`` in app.py.
    """
    if metric == "share":
        total = float(aggregated["crime_count"].sum())
        if total > 0:
            values = aggregated["crime_count"] / total * 100.0
        else:
            values = pd.Series(0.0, index=aggregated.index)
    else:
        column = resolve_metric(metric, severity_basis)
        values = aggregated[column]

    values = values.fillna(0.0).astype(float)
    vmin = float(values.min()) if len(values) else 0.0
    vmax = max(float(values.max()) if len(values) else 0.0, 1.0)
    return values, vmin, vmax
