// Typed fetch client. URLs are relative; the Vite dev server proxies /api to
// the FastAPI backend.

import type {
    AllocationRequest,
  AllocationResponse,
  BoundaryCollection,
  Level,
  MapRequest,
  MapResponse,
  MetaResponse,
  TimeseriesResponse,
  WeightRow,
} from './types'

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Unexpected error'
}

async function getJSON<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) {
    throw new Error(`GET ${url} failed: ${res.status} ${res.statusText}`)
  }
  return (await res.json()) as T
}

export async function fetchMeta(city: string): Promise<MetaResponse> {
  const params = new URLSearchParams({ city: city.toLowerCase() })
  return getJSON<MetaResponse>(`/api/meta?${params}`)
}

export async function fetchWeights(): Promise<WeightRow[]> {
  return getJSON<WeightRow[]>('/api/weights')
}

export async function fetchBoundaries(level: Level): Promise<BoundaryCollection> {
  // Boundaries are static assets (pre-baked by scripts/prepare-static.mjs),
  // served by Vite's public/ dir in dev and the Vercel CDN in production.
  return getJSON<BoundaryCollection>(`/boundaries/${level}.json`)
}

export async function fetchMap(req: MapRequest): Promise<MapResponse> {
  try {
    const res = await fetch('/api/map', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    })
    if (!res.ok) {
      throw new Error(`POST /api/map failed: ${res.status} ${res.statusText}`)
    }
    return (await res.json()) as MapResponse
  } catch (error: unknown) {
    throw new Error(errorMessage(error))
  }
}

export async function fetchTimeseries(
  lsoaCode: string,
  categories: string[],
  city: string,
): Promise<TimeseriesResponse> {
  const p = new URLSearchParams({ lsoa_code: lsoaCode, city: city.toLowerCase() })
  // Repeated `categories` params match the backend's list query param; an empty
  // selection means "all categories" (param omitted).
  for (const c of categories) p.append('categories', c)
  return getJSON<TimeseriesResponse>(`/api/timeseries?${p}`)
}

export async function fetchAllocation(req: AllocationRequest): Promise<AllocationResponse> {
  const p = new URLSearchParams({
    city: req.city.toLowerCase(),
    total_units: String(req.totalUnits),
    model: req.model,
  })
  if (req.alpha !== undefined) p.set('alpha', String(req.alpha))
  if (req.beta !== undefined) p.set('beta', String(req.beta))
  if (req.maxCapFactor !== undefined) p.set('max_cap_factor', String(req.maxCapFactor))
  if (req.equityFloor !== undefined) p.set('equity_floor', String(req.equityFloor))
  if (req.minUnitsPerLsoa !== undefined) p.set('min_units_per_lsoa', String(req.minUnitsPerLsoa))
  return getJSON<AllocationResponse>(`/api/allocation?${p}`)
}
