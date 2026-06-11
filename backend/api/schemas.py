"""Pydantic request/response models. Mirror these in frontend/src/lib/types.ts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Level = Literal["lsoa", "ward", "borough"]
Metric = Literal["raw", "share", "severity", "preventability", "composite"]
SeverityBasis = Literal["mean", "median"]


class CategoryMeta(BaseModel):
    name: str
    preventability_tier: str
    preventability_confidence: str
    preventability_anchor: str


class MetaResponse(BaseModel):
    years: list[int]
    months: list[int]
    # Distinct (year, month) pairs actually present in the data, sorted
    # chronologically. Drives the time-animation slider.
    periods: list[tuple[int, int]]
    categories: list[CategoryMeta]
    boroughs: list[str]
    tiers: list[str]
    city: str


class MapRequest(BaseModel):
    categories: list[str] = Field(default_factory=list)  # empty = all
    tier: str = "All tiers"
    year: int | None = None  # None / "All years" = all
    months: list[int] = Field(default_factory=list)  # empty = all
    borough: str = "All boroughs"
    level: Level = "lsoa"
    metric: Metric = "raw"
    severity_basis: SeverityBasis = "mean"
    city: str = "london"


class MapResponse(BaseModel):
    # Keyed by feature id (lsoa_code / ward_code / borough). Every unit at the
    # level is present (0-filled), matching the Streamlit left-join behaviour.
    values: dict[str, float]
    crime_counts: dict[str, float]
    vmin: float
    vmax: float
