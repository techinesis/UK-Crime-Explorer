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
    city: filters.city,
  }
}

/**
 * Cache the LSOA -> Borough lookup so we do not fetch boundaries repeatedly.
 * This is useful because forecast_dashboard_long.json has LSOA code but may not include Borough.
 */
let lsoaBoroughLookupPromise: Promise<Record<string, string>> | null = null

async function getLsoaBoroughLookup() {
  if (!lsoaBoroughLookupPromise) {
    lsoaBoroughLookupPromise = buildLsoaBoroughLookup()
  }

  return lsoaBoroughLookupPromise
}

async function buildLsoaBoroughLookup(): Promise<Record<string, string>> {
  try {
    const boundaryData: any = await fetchBoundaries('lsoa' as any)
    const features = Array.isArray(boundaryData?.features) ? boundaryData.features : []

    const lookup: Record<string, string> = {}

    for (const feature of features) {
      const properties = feature?.properties ?? {}

      const lsoaCode = pickProperty(properties, [
        'lsoa_code',
        'LSOA code',
        'LSOA Code',
        'LSOA11CD',
        'LSOA21CD',
        'code',
        'id',
      ])

      const borough = pickProperty(properties, [
        'borough',
        'Borough',
        'borough_name',
        'Borough name',
        'lad_name',
        'LAD name',
        'LAD22NM',
        'local_authority',
      ])

      if (lsoaCode && borough) {
        lookup[normaliseLookupKey(lsoaCode)] = String(borough)
      }
    }

    console.log('LSOA → Borough lookup size:', Object.keys(lookup).length)

    return lookup
  } catch (error) {
    console.warn('Could not build LSOA to borough lookup:', error)
    return {}
  }
}

function pickProperty(properties: Record<string, any>, possibleNames: string[]) {
  for (const name of possibleNames) {
    if (properties[name] !== undefined && properties[name] !== null) {
      return properties[name]
    }
  }

  const normalisedNames = possibleNames.map(normaliseColumnName)

  for (const [key, value] of Object.entries(properties)) {
    if (normalisedNames.includes(normaliseColumnName(key))) {
      return value
    }
  }

  return null
}

async function fetchForecastMap(filters: FilterState) {
  const response = await fetch('/forecast_dashboard_long.json')

  if (!response.ok) {
    throw new Error('Could not load forecast_dashboard_long.json')
  }

  const data = await response.json()
  const lsoaBoroughLookup = await getLsoaBoroughLookup()

  const rawRows = Array.isArray(data)
    ? data
    : Array.isArray(data.rows)
      ? data.rows
      : Array.isArray(data.data)
        ? data.data
        : []

  const rows = rawRows
    .map((row: any) => {
      const monthString = String(row.Month ?? row.month ?? row.period ?? '')
      const year = Number(monthString.slice(0, 4))
      const monthNum = Number(monthString.slice(5, 7))

      const lsoaCode =
        row['LSOA code'] ??
        row['LSOA Code'] ??
        row.lsoa_code ??
        row.lsoaCode ??
        row.area_code ??
        row.unit_id ??
        null

      const crimeType =
        row['Crime type'] ??
        row['Crime Type'] ??
        row.crime_type ??
        row.category ??
        row.major_category ??
        null

      const borough =
        row.Borough ??
        row.borough ??
        row['Borough name'] ??
        row.borough_name ??
        lsoaBoroughLookup[normaliseLookupKey(lsoaCode)] ??
        null

      const value =
        row.predicted_crimes ??
        row.prediction ??
        row.predicted ??
        row.forecast ??
        row.forecast_crimes ??
        row.y_pred ??
        row.value ??
        row.demand ??
        row.crimes ??
        row.total_crimes ??
        0

      return {
        ...row,
        month: monthString,
        year,
        month_num: monthNum,
        lsoa_code: lsoaCode,
        crime_type: crimeType,
        borough,
        value: Number(value),
      }
    })
    .filter((row: any) => {
      return row.month && row.lsoa_code && Number.isFinite(row.value)
    })

  const availableMonths = Array.from(new Set(rows.map((row: any) => String(row.month)))).sort()

  const horizon = Math.max(1, Number(filters.forecastHorizon ?? 12))
  const horizonMonths = availableMonths.slice(0, horizon)

  const hasBoroughInfo = rows.some((row: any) => row.borough)

  const filteredRows = rows.filter((row: any) => {
    const matchesHorizon = horizonMonths.includes(row.month)

    const matchesBorough =
      !filters.borough ||
      filters.borough === 'All boroughs' ||
      !hasBoroughInfo ||
      row.borough === filters.borough

    const matchesCategory =
      !filters.categories ||
      filters.categories.length === 0 ||
      filters.categories.some((category) => {
        return normaliseCategory(category) === normaliseCategory(row.crime_type)
      })

    return matchesHorizon && matchesBorough && matchesCategory
  })

  const values: Record<string, number> = {}

  for (const row of filteredRows) {
    const key =
      filters.level === 'borough'
        ? row.borough
        : filters.level === 'ward'
          ? row.ward_code ?? row.ward ?? row.lsoa_code
          : row.lsoa_code

    if (!key) continue

    values[key] = (values[key] ?? 0) + row.value
  }

  const numericValues = Object.values(values)
  const totalPredicted = numericValues.reduce((sum, value) => sum + value, 0)

  console.log('========== FORECAST DEBUG ==========')
  console.log('Selected forecast horizon:', horizon)
  console.log('Available forecast months:', availableMonths)
  console.log('Months used for this horizon:', horizonMonths)
  console.log('Raw forecast rows:', rawRows.length)
  console.log('Cleaned forecast rows:', rows.length)
  console.log('Filtered forecast rows:', filteredRows.length)
  console.log('Map level:', filters.level)
  console.log('Selected borough:', filters.borough)
  console.log('Selected categories:', filters.categories)
  console.log('Number of map units:', numericValues.length)
  console.log('Total predicted demand:', totalPredicted)
  console.log('Min value:', numericValues.length > 0 ? Math.min(...numericValues) : 0)
  console.log('Max value:', numericValues.length > 0 ? Math.max(...numericValues) : 1)
  console.log('First cleaned forecast row:', rows[0])
  console.log('First filtered forecast row:', filteredRows[0])
  console.log('====================================')

  return {
    values,
    crime_counts: values,
    rows: filteredRows,
    vmin: numericValues.length > 0 ? Math.min(...numericValues) : 0,
    vmax: numericValues.length > 0 ? Math.max(...numericValues) : 1,
    total: totalPredicted,
    isForecast: true,
    isPrototypeForecast: false,
    forecastHorizon: horizon,
    forecastModel: 'xgboost',
    forecastMonths: horizonMonths,
    forecastNote: 'Forecast based on the generated model output from forecast_dashboard_long.json.',
  }
}

function normaliseCategory(value: unknown) {
  return String(value ?? '')
    .toLowerCase()
    .replace(/[_-]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function normaliseColumnName(value: unknown) {
  return String(value ?? '')
    .toLowerCase()
    .replace(/[_-]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function normaliseLookupKey(value: unknown) {
  return String(value ?? '')
    .toUpperCase()
    .trim()
}

/** Boundaries cached forever per level + map values for the active filters. */
export function useCrimeData(filters: FilterState) {
  const boundaries = useQuery({
    queryKey: ['boundaries', filters.level, filters.city],
    queryFn: () => fetchBoundaries(filters.level),
    staleTime: Infinity,
  })

  const request = toMapRequest(filters)

  const map = useQuery({
    queryKey: [
      'map',
      filters.mode,
      request,
      filters.forecastHorizon,
      filters.city,
    ],
    queryFn: () => {
      if (filters.mode === 'forecast') {
        return fetchForecastMap(filters)
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
      filters.city,
    ],
    queryFn: () => {
      if (filters.mode === 'forecast') {
        return fetchForecastMap({
          ...filters,
          level: 'borough',
        })
      }

      return fetchMap(boroughRequest)
    },
    placeholderData: (previousData) => previousData,
  })

  return { boundaries, map, boroughMap }
}
