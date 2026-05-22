import { useQuery } from '@tanstack/react-query'
import { fetchBoundaries, fetchMap } from '../lib/api'
import type { MapRequest } from '../lib/types'
import type { FilterState } from './useFilters'

function toMapRequest(f: FilterState): MapRequest {
  return {
    categories: f.categories,
    tier: f.tier,
    year: f.year,
    months: f.months,
    borough: f.borough,
    level: f.level,
    metric: f.metric,
    severity_basis: f.severityBasis,
  }
}

/** Boundaries (cached forever per level) + the per-filter values map. */
export function useCrimeData(filters: FilterState) {
  const boundaries = useQuery({
    queryKey: ['boundaries', filters.level],
    queryFn: () => fetchBoundaries(filters.level),
    staleTime: Infinity, // geometry is static for a geometry version
  })

  const request = toMapRequest(filters)
  const map = useQuery({
    queryKey: ['map', request],
    queryFn: () => fetchMap(request),
    placeholderData: (prev) => prev, // keep last map while refetching (no flicker)
  })

  // Borough-level aggregation of the same filters, for the always-on borough
  // summary table. When level is already 'borough' this shares map's cache.
  const boroughRequest = { ...request, level: 'borough' as const }
  const boroughMap = useQuery({
    queryKey: ['map', boroughRequest],
    queryFn: () => fetchMap(boroughRequest),
    placeholderData: (prev) => prev,
  })

  return { boundaries, map, boroughMap }
}
