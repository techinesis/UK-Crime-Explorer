"""Smoke test 3: composite-metric invariants, exercised directly on real data.

Calls core.composite against the enriched crime frame (no API) to guard the
crime_count x severity x preventability identity, the Anti-social-behaviour
severity coercion, and the mean-vs-median CCHI divergence that the severity_basis
toggle depends on.
"""

from __future__ import annotations

import numpy as np
import pytest

from core.composite import add_composite_columns
from core.data import get_crime_long


@pytest.mark.smoke
def test_composite_invariants():
    df = get_crime_long("london")
    enriched = add_composite_columns(df)

    # 1. Identity: composite = count x severity(mean) x preventability, per row.
    cat = "Violence and sexual offences"
    rows = enriched[enriched["category"] == cat]
    assert not rows.empty, f"no rows for {cat!r}"
    expected = rows["crime_count"] * rows["severity_weight_mean"] * rows["preventability_multiplier"]
    assert np.allclose(rows["composite_weighted_mean"], expected), (
        f"composite identity broken for {cat!r}"
    )

    # 2. Anti-social behaviour has no CCHI severity (NaN -> coerced to 0), so its
    #    severity-weighted demand is 0 even where crimes were recorded.
    asb = enriched[enriched["category"] == "Anti-social behaviour"]
    assert not asb.empty, "no Anti-social behaviour rows"
    assert (asb["severity_weight_mean"] == 0).all(), "ASB severity weight not coerced to 0"
    nonzero = asb[asb["crime_count"] > 0]
    assert not nonzero.empty, "expected some recorded Anti-social behaviour crime"
    assert (nonzero["severity_weighted_mean"] == 0).all(), "ASB severity-weighted value not 0"

    # 3. Mean and median CCHI must diverge for at least one category by >10%, so
    #    the severity_basis toggle is not a silent no-op. The per-category weight
    #    is constant, so its mean/median ratio drives the severity-weighted value.
    per_cat = df.groupby("category", observed=True)[
        ["severity_weight_mean", "severity_weight_median"]
    ].first()
    diverged = any(
        mean_w > 0 and abs(mean_w - median_w) / mean_w > 0.10
        for mean_w, median_w in per_cat.itertuples(index=False, name=None)
    )
    assert diverged, "no category's mean vs median CCHI severity differs by >10%"
