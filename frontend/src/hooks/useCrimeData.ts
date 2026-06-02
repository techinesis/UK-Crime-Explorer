import { useQuery } from '@tanstack/react-query'
import { fetchBoundaries, fetchMap } from '../lib/api'
import type { MapRequest } from '../lib/types'
import type { FilterState } from './useFilters'

function toMapRequest(filters: FilterState): MapRequest {
  return {
    categories: filters.categories,
    tier: filters.tier,
    year: filters.year,
    months: filters.months,
    borough: filters.borough,
    level: filters.level,
    metric: filters.metric,
    severity_basis: filters.severityBasis,
  }
}

/**
 * Temporary forecast prototype.
 *
 * Because real forecasted data is not available yet, this creates a transparent
 * placeholder forecast from the existing historical map values.
 *
 * Later, replace fetchForecastPrototypeMap() with a real fetchForecast() API call.
 */
async function fetchForecastPrototypeMap(request: MapRequest, filters: FilterState) {
  const historicalMap = await fetchMap(request)

  return applyPrototypeForecast(historicalMap, {
    horizon: filters.forecastHorizon,
    model: filters.forecastModel,
  })
}

type PrototypeForecastOptions = {
  horizon: number
  model: string
}

function applyPrototypeForecast(map: any, options: PrototypeForecastOptions) {
  if (!map) return map

  const factor = getPrototypeForecastFactor(options)

  const nextMap = {
    ...map,
    isForecast: true,
    isPrototypeForecast: true,
    forecastHorizon: options.horizon,
    forecastModel: options.model,
    forecastNote:
      'Prototype forecast only: values are estimated from historical demand until real model output is connected.',
  }

  const collectedValues: number[] = []

  /**
   * Most likely structure:
   * {
   *   values: {
   *     "E01000001": 123,
   *     "E01000002": 98
   *   },
   *   vmin: 0,
   *   vmax: 123
   * }
   */
  if (map.values && typeof map.values === 'object' && !Array.isArray(map.values)) {
    const forecastValues: Record<string, number> = {}

    for (const [unitId, value] of Object.entries(map.values)) {
      if (typeof value === 'number' && Number.isFinite(value)) {
        const predicted = makePrototypePrediction(value, factor, unitId)
        forecastValues[unitId] = predicted
        collectedValues.push(predicted)
      }
    }

    nextMap.values = forecastValues
  }

  /**
   * Alternative possible structure:
   * {
   *   rows: [
   *     { unit_id: "...", value: 123 },
   *     ...
   *   ]
   * }
   */
  if (Array.isArray(map.rows)) {
    nextMap.rows = map.rows.map((row: any) => scaleForecastRow(row, factor, collectedValues))
  }

  /**
   * Alternative possible structure:
   * {
   *   data: [
   *     { unit_id: "...", value: 123 },
   *     ...
   *   ]
   * }
   */
  if (Array.isArray(map.data)) {
    nextMap.data = map.data.map((row: any) => scaleForecastRow(row, factor, collectedValues))
  }

  if (collectedValues.length > 0) {
    nextMap.vmin = Math.min(...collectedValues)
    nextMap.vmax = Math.max(...collectedValues)
  }

  return nextMap
}

function getPrototypeForecastFactor(options: PrototypeForecastOptions) {
  const horizon = Math.max(1, options.horizon || 1)

  /**
   * These are not real model parameters.
   * They only create a visible prototype effect for the dashboard.
   */
  if (options.model === 'baseline') {
    return 1 + horizon * 0.015
  }

  if (options.model === 'xgboost') {
    return 1 + horizon * 0.025
  }

  return 1 + horizon * 0.02
}

function makePrototypePrediction(value: number, factor: number, unitId?: string) {
  /**
   * Add a tiny deterministic variation by unit so the forecast does not look like
   * a flat multiplication everywhere. This is still only a prototype.
   */
  const variation = unitId ? getStableVariation(unitId) : 1
  const predicted = value * factor * variation

  return Number(predicted.toFixed(2))
}

function getStableVariation(input: string) {
  let hash = 0

  for (let index = 0; index < input.length; index += 1) {
    hash = (hash * 31 + input.charCodeAt(index)) >>> 0
  }

  /**
   * Range: roughly 0.95 to 1.05
   */
  return 0.95 + (hash % 100) / 1000
}

function scaleForecastRow(row: any, factor: number, collectedValues: number[]) {
  const unitId =
    row.unit_id ??
    row.unitId ??
    row.id ??
    row.lsoa_code ??
    row.ward_code ??
    row.borough ??
    undefined

  const nextRow = { ...row }

  const possibleValueFields = [
    'value',
    'metric',
    'demand',
    'prediction',
    'predicted',
    'raw',
    'count',
    'total_crimes',
  ]

  for (const field of possibleValueFields) {
    const value = row[field]

    if (typeof value === 'number' && Number.isFinite(value)) {
      const predicted = makePrototypePrediction(value, factor, String(unitId ?? field))
      nextRow[field] = predicted
      collectedValues.push(predicted)
    }
  }

  nextRow.isForecast = true
  nextRow.isPrototypeForecast = true

  return nextRow
}

/** Boundaries cached forever per level + map values for the active filters. */
export function useCrimeData(filters: FilterState) {
  const boundaries = useQuery({
    queryKey: ['boundaries', filters.level],
    queryFn: () => fetchBoundaries(filters.level),
    staleTime: Infinity,
  })

  const request = toMapRequest(filters)

  const map = useQuery({
    queryKey: ['map', filters.mode, request, filters.forecastHorizon, filters.forecastModel],
    queryFn: () => {
      if (filters.mode === 'forecast') {
        return fetchForecastPrototypeMap(request, filters)
      }

      return fetchMap(request)
    },
    placeholderData: (previousData) => previousData,
  })

  const boroughRequest = {
    ...request,
    level: 'borough' as const,
  }

  const boroughMap = useQuery({
    queryKey: [
      'map',
      'borough-summary',
      filters.mode,
      boroughRequest,
      filters.forecastHorizon,
      filters.forecastModel,
    ],
    queryFn: () => {
      if (filters.mode === 'forecast') {
        return fetchForecastPrototypeMap(boroughRequest, filters)
      }

      return fetchMap(boroughRequest)
    },
    placeholderData: (previousData) => previousData,
  })

  return { boundaries, map, boroughMap }
}