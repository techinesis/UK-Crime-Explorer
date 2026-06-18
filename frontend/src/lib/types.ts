// Mirrors backend/api/schemas.py. Keep in sync with the Pydantic models.

export type Level = 'lsoa' | 'ward' | 'borough'
export type Metric = 'raw' | 'share' | 'severity' | 'preventability' | 'composite'
export type SeverityBasis = 'mean' | 'median'

export interface CategoryMeta {
  name: string
  preventability_tier: string
  preventability_confidence: string
  preventability_anchor: string
}

export interface MetaResponse {
  years: number[]
  months: number[]
  periods: Array<[number, number]> // distinct (year, month) pairs, chronological
  categories: CategoryMeta[]
  boroughs: string[]
  tiers: string[]
  city: string
}

export interface MapRequest {
  categories: string[] // empty = all
  tier: string
  year: number | null // null = all
  months: number[] // empty = all
  borough: string
  level: Level
  metric: Metric
  severity_basis: SeverityBasis
  city: string
}

export interface MapResponse {
  values: Record<string, number>
  crime_counts: Record<string, number>
  vmin: number
  vmax: number
}

export interface WeightRow {
  category: string
  severity_weight_mean: number | null
  severity_weight_median: number | null
  preventability_multiplier: number | null
  preventability_tier: string
  preventability_confidence: string
  preventability_anchor: string
}

export interface AllocationRequest {
  city: string
  totalUnits: number
  model: string
  alpha?: number
  beta?: number
  maxCapFactor?: number
  equityFloor?: number
  minUnitsPerLsoa?: number
}

export interface AllocationEntry {
  lsoa_code: string
  lsoa_name: string
  borough: string
  units: number
  schedule: number[][] // [day][hour]
}

export interface AllocationResponse {
  city: string
  total_units: number
  model: string
  warning?: string
  entries: AllocationEntry[]
}

export interface TimeseriesPoint {
  year: number
  month: number
  count: number
}

export interface TimeseriesResponse {
  lsoa_code: string
  lsoa_name: string
  borough: string
  categories: string[]
  series: TimeseriesPoint[]
}

// GeoJSON shape for the boundary layers (geometry + trimmed props).
import type { Feature, FeatureCollection, Geometry } from 'geojson'

export type BoundaryProps = Record<string, string | number | null>
export type BoundaryFeature = Feature<Geometry, BoundaryProps>
export type BoundaryCollection = FeatureCollection<Geometry, BoundaryProps>
