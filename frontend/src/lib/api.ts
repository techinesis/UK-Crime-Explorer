// Typed fetch client. URLs are relative; the Vite dev server proxies /api to
// the FastAPI backend.

import type {
  AllocationResponse,
  BoundaryCollection,
  Level,
  MapRequest,
  MapResponse,
  MetaResponse,
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

export async function fetchAllocation(
  city: string,
  totalUnits: number,
  model: string,
): Promise<AllocationResponse> {
  const params = new URLSearchParams({ city: city.toLowerCase(), total_units: String(totalUnits), model })
  return getJSON<AllocationResponse>(`/api/allocation?${params}`)
}
