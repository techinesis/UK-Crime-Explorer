"""Allocation payload builder, shared between the HTTP route and the chat tool.

``_allocation_payload`` used to live in ``api/main.py``. It was moved here so that
``core/chat.py``'s ``get_allocation`` tool can import it **without** importing
``api.main`` — that would be a circular import
(``core.chat -> api.main -> api.chat -> core.chat``). This module imports only
downhill (``allocation``, ``core.composite``, ``core.data``) plus the leaf
``api.schemas`` (pydantic DTOs, no back-edge), so neither ``api.main`` nor
``core.chat`` closes a cycle through it.

Behaviour is identical to the original: same signature, same ``@lru_cache(maxsize=64)``,
same ``AllocationResponse`` shape. ``api/main.py`` now imports ``_allocation_payload``
from here for the ``/api/allocation`` route, and ``core/chat.py`` imports the small
``default_allocation`` wrapper (production-default parameters, cached per
``(city, model, total_units)``).
"""

from __future__ import annotations

from functools import lru_cache
from typing import no_type_check

import numpy as np
import pandas as pd

from allocation import (
    _DAILY_HOURLY_WEIGHTS,
    ANTI_OVER_POLICING_WEIGHTS,
    AllocationInfeasibleError,
    AveragingModel,
    LPModel,
    RawlsModel,
)

from api.schemas import AllocationEntry, AllocationResponse
from core.composite import add_composite_columns
from core.data import get_forecast_long

_CAT_TEMPLATES: dict[str, np.ndarray] = {}
for _cat, (_hw, _dw) in _DAILY_HOURLY_WEIGHTS.items():
    _h = np.array(_hw, dtype=float)
    _h /= _h.sum()
    _d = np.array(_dw, dtype=float)
    _d /= _d.sum()
    _CAT_TEMPLATES[_cat] = np.outer(_d, _h)

_DEFAULT_TEMPLATE = _CAT_TEMPLATES.get("Other crime", np.ones((7, 24)) / (7 * 24))


def _apply_anti_over_policing_weights(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    factors = out["category"].map(ANTI_OVER_POLICING_WEIGHTS).fillna(1.0)
    out["crime_count"] = out["crime_count"] * factors.to_numpy()
    return add_composite_columns(out)


def _lsoa_weekly_schedule(crime_shares: dict, units: int, active: float = 0.33) -> list[list[int]]:
    total = sum(crime_shares.values())
    if total <= 0:
        return [[1] * 24 for _ in range(7)]
    template = np.zeros((7, 24), dtype=float)
    for cat, count in crime_shares.items():
        template += (count / total) * _CAT_TEMPLATES.get(cat, _DEFAULT_TEMPLATE)
    mean_val = template.mean()
    if mean_val > 0:
        template /= mean_val
    return np.maximum(np.round(template * units * active).astype(int), 1).tolist()


@no_type_check  # type checkers aren't too happy about itertuples
@lru_cache(maxsize=64)
def _allocation_payload(
    city: str,
    total_units: int,
    model: str,
    alpha: float,
    beta: float,
    max_cap_factor: float,
    equity_floor: float,
    min_units_per_lsoa: int,
) -> AllocationResponse:
    df = _apply_anti_over_policing_weights(get_forecast_long(city))
    resp = AllocationResponse(
        city=city,
        total_units=total_units,
        model=model,
        warning="",
        entries=[],
    )

    lsoa_name_map = df.groupby("lsoa_code")["lsoa_name"].first()
    borough_map = df.groupby("lsoa_code")["borough"].first()

    warning: str | None = None
    if model == "lp":
        alloc_model = LPModel(
            weighted_column="composite_weighted_mean",
            total_units=total_units,
            alpha=alpha,
            beta=beta,
            gamma=max(0.0, 1.0 - alpha - beta),
            max_cap_factor=max_cap_factor,
            equity_floor=equity_floor,
            min_units_per_lsoa=min_units_per_lsoa,
        )
    elif model == "rawls":
        alloc_model = RawlsModel(
            weighted_column="composite_weighted_mean",
            total_units=total_units,
            min_units_per_lsoa=min_units_per_lsoa,
        )
    else:
        alloc_model = AveragingModel(total_units=total_units)

    try:
        allocated_df = alloc_model.allocate(df)
    except AllocationInfeasibleError as e:
        warning = f"Allocation was infeasible with the given parameters ({e})."
        resp.warning = warning
        return resp

    allocated_df["lsoa_name"] = (
        allocated_df["lsoa_code"].map(lsoa_name_map).fillna(allocated_df["lsoa_code"])
    )
    if "borough" not in allocated_df.columns:
        allocated_df["borough"] = allocated_df["lsoa_code"].map(borough_map)

    crime_by_lsoa: dict[str, dict[str, float]] = {}
    for row in (
        df
        .groupby(["lsoa_code", "category"])["crime_count"]
        .sum()
        .reset_index()
        .itertuples(index=False)
    ):
        crime_by_lsoa.setdefault(str(row.lsoa_code), {})[str(row.category)] = float(row.crime_count)

    entries = []
    for row in allocated_df.itertuples(index=False):
        lsoa = str(row.lsoa_code)
        u = max(1, int(round(float(row.units))))
        shares = crime_by_lsoa.get(lsoa, {"Other crime": 1.0})
        entries.append(
            AllocationEntry(
                lsoa_code=lsoa,
                lsoa_name=str(row.lsoa_name),
                borough=str(row.borough),
                units=float(row.units),
                schedule=_lsoa_weekly_schedule(shares, u),
            )
        )

    resp.warning = warning
    resp.entries = entries
    return resp


# Production-default parameters used by the dashboard's /api/allocation default view.
_PROD_ALPHA = 0.6
_PROD_BETA = 0.25
_PROD_MAX_CAP_FACTOR = 2.0
_PROD_EQUITY_FLOOR = 0.7
_PROD_MIN_UNITS_PER_LSOA = 6


@lru_cache(maxsize=8)
def default_allocation(city: str, model: str, total_units: int) -> AllocationResponse:
    """Allocation for the production-default parameters, cached per (city, model, total_units).

    The chat's ``get_allocation`` tool only exposes ``city``/``model``/``total_units``,
    so those three fully determine the solve; this small cache keeps repeated default
    calls from re-running the LP. ``cache_info()`` reports the chat-layer hit rate.
    """
    return _allocation_payload(
        city,
        total_units,
        model,
        _PROD_ALPHA,
        _PROD_BETA,
        _PROD_MAX_CAP_FACTOR,
        _PROD_EQUITY_FLOOR,
        _PROD_MIN_UNITS_PER_LSOA,
    )
