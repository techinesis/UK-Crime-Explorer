import { useCallback, useState } from 'react'
import type { Level, Metric, SeverityBasis } from '../lib/types'

export type ForecastMode = 'historical' | 'forecast'
export type ForecastModel = 'xgboost' | 'baseline'
export type AllocationModel = typeof ALLOCATION_MODELS[number]['value']

export interface FilterState {
  categories: string[] // empty = all
  tier: string
  year: number | null // null = all
  months: number[] // empty = all
  borough: string
  level: Level
  metric: Metric
  severityBasis: SeverityBasis
  city: string

  // Forecasting options
  mode: ForecastMode
  forecastHorizon: number
  forecastModel: ForecastModel

  // Allocation stuff
  allocationModel: AllocationModel
  totalUnits: number

  // LP Parameters
  allocAlpha: number // weight for severity score
  allocBeta: number // weight for crime volume
  allocMaxCapFactor: number
  allocEquityFloor: number

  // LP and Rawls Parameters
  allocMinUnitsPerLsoa: number
}

export const TIER_ALL = 'All tiers'
export const YEAR_ALL = 'All years'
export const BOROUGH_ALL = 'All boroughs'
export const CITIES = ['London', 'Birmingham', 'Manchester', 'Liverpool']
export const ALLOCATION_MODELS = [
  { value: 'lp', label: 'LP Optimisation' },
  { value: 'rawls', label: 'Rawls LP Optimisation' },
  { value: 'baseline', label: 'Proportional baseline' },
]

export const DEFAULT_FILTERS: FilterState = {
  categories: [],
  tier: TIER_ALL,
  year: null,
  months: [],
  borough: BOROUGH_ALL,
  level: 'lsoa',
  metric: 'raw',
  severityBasis: 'mean',
  city: CITIES[0],

  // Forecasting defaults
  mode: 'historical',
  forecastHorizon: 1,
  forecastModel: 'xgboost',

  allocationModel: ALLOCATION_MODELS[0].value,
  totalUnits: 33_000,

  allocAlpha: 0.6,
  allocBeta: 0.25,
  allocMaxCapFactor: 2.0,
  allocEquityFloor: 0.7,

  allocMinUnitsPerLsoa: 6,
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

export const FORECAST_MODE_OPTIONS: Array<{ value: ForecastMode; label: string }> = [
  { value: 'historical', label: 'Historical' },
  { value: 'forecast', label: 'Forecast' },
]

export const FORECAST_HORIZON_OPTIONS: Array<{ value: number; label: string }> = [
  { value: 1, label: 'Next month' },
  { value: 3, label: 'Next 3 months' },
  { value: 6, label: 'Next 6 months' },
  { value: 12, label: 'Next 12 months' },
]

export const FORECAST_MODEL_OPTIONS: Array<{ value: ForecastModel; label: string }> = [
  { value: 'xgboost', label: 'XGBoost' },
  { value: 'baseline', label: 'Seasonal baseline' },
]

/** Human-readable caption for the active metric, used in legend and recap. */
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
    setFilters((prev) => {
      const isForecast = patch.mode ? patch.mode === "forecast" : prev.mode === "forecast"
      if (isForecast) {
        // XXX: forecasting currently forces London, if functionality changes this should be undone
        patch.city = "london"
      }
      return ({ ...prev, ...patch })
    })
  }, [])

  return { filters, update, setFilters }
}
