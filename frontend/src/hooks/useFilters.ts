import { useCallback, useState } from 'react'
import type { Level, Metric, SeverityBasis } from '../lib/types'

export interface FilterState {
  categories: string[] // empty = all
  tier: string
  year: number | null // null = all
  months: number[] // empty = all
  borough: string
  level: Level
  metric: Metric
  severityBasis: SeverityBasis
}

export const TIER_ALL = 'All tiers'
export const YEAR_ALL = 'All years'
export const BOROUGH_ALL = 'All boroughs'

export const DEFAULT_FILTERS: FilterState = {
  categories: [],
  tier: TIER_ALL,
  year: null,
  months: [],
  borough: BOROUGH_ALL,
  level: 'lsoa',
  metric: 'raw',
  severityBasis: 'mean',
}

export const METRIC_OPTIONS: Array<{ value: Metric; label: string }> = [
  { value: 'raw', label: 'Raw crime count' },
  { value: 'share', label: 'Crime share within selected data' },
  { value: 'severity', label: 'Severity-weighted' },
  { value: 'preventability', label: 'Preventability-filtered' },
  { value: 'composite', label: 'Composite (severity × preventability)' },
]

export const LEVEL_OPTIONS: Array<{ value: Level; label: string }> = [
  { value: 'lsoa', label: 'LSOA' },
  { value: 'ward', label: 'Ward' },
  { value: 'borough', label: 'Borough' },
]

/** Human-readable caption for the active metric (used in legend + recap). */
export function metricCaption(metric: Metric, basis: SeverityBasis): string {
  const basisLabel = basis === 'mean' ? 'Mean CCHI' : 'Median CCHI'
  switch (metric) {
    case 'raw':
      return 'Recorded crime count'
    case 'share':
      return 'Crime share within selected data (%)'
    case 'severity':
      return `Severity-weighted crime count (${basisLabel})`
    case 'preventability':
      return 'Preventability-weighted crime count'
    case 'composite':
      return `Composite severity × preventability (${basisLabel})`
  }
}

export function useFilters(initial: FilterState = DEFAULT_FILTERS) {
  const [filters, setFilters] = useState<FilterState>(initial)

  const update = useCallback((patch: Partial<FilterState>) => {
    setFilters((prev) => ({ ...prev, ...patch }))
  }, [])

  return { filters, update, setFilters }
}
