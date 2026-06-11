import { useEffect, useMemo, useState } from 'react'
import DeckGL from '@deck.gl/react'
import { GeoJsonLayer } from '@deck.gl/layers'
import { Map } from 'react-map-gl/maplibre'
import type { Feature, Geometry } from 'geojson'
import { rgbaForValue, type RGBA } from '../lib/colors'
import type { BoundaryCollection, BoundaryProps, Level, MapResponse, MetaResponse } from '../lib/types'
import type { Theme } from '../hooks/useTheme'
import { CITIES } from '../hooks/useFilters'

const BASEMAP: Record<Theme, string> = {
  light: 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json',
  dark: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
}

const LINE_COLOR: Record<Theme, RGBA> = {
  light: [100, 116, 139, 90], // slate-500, visible on the pale basemap
  dark: [255, 255, 255, 60],
}

const TOOLTIP_STYLE: Record<Theme, { backgroundColor: string; color: string }> = {
  light: { backgroundColor: 'rgba(255,255,255,0.96)', color: '#111827' },
  dark: { backgroundColor: 'rgba(15,23,42,0.95)', color: '#f1f5f9' },
}

interface Dict {
  [key: string]: any
}

const CITY_VIEWS: Dict = {
  "london": { longitude: -0.1278, latitude: 51.5074, zoom: 9.2, minZoom: 9, maxZoom: 16 },
  "birmingham": { longitude: -1.89983, latitude: 52.48142, zoom: 9.2, minZoom: 9, maxZoom: 16 },
  "manchester": { longitude: -2.23743, latitude: 53.48095, zoom: 9.2, minZoom: 9, maxZoom: 16 },
  "liverpool": { longitude: -2.983333, latitude: 53.400002, zoom: 9.2, minZoom: 9, maxZoom: 16 },
}

const ID_PROP: Record<Level, string> = {
  lsoa: 'lsoa_code',
  ward: 'ward_code',
  borough: 'borough',
}

interface ViewState {
  longitude: number
  latitude: number
  zoom: number
  minZoom?: number
  maxZoom?: number
}

type BoundaryFeature = Feature<Geometry, BoundaryProps>

function eachCoord(geometry: Geometry | null, cb: (lng: number, lat: number) => void): void {
  if (!geometry) return
  if (geometry.type === 'Polygon') {
    for (const ring of geometry.coordinates) for (const [lng, lat] of ring) cb(lng, lat)
  } else if (geometry.type === 'MultiPolygon') {
    for (const poly of geometry.coordinates)
      for (const ring of poly) for (const [lng, lat] of ring) cb(lng, lat)
  }
}

/** Centre + zoom for a borough's features, or null if none match. */
function boroughView(features: BoundaryFeature[], borough: string, city: string): ViewState | null {
  let minLng = Infinity
  let minLat = Infinity
  let maxLng = -Infinity
  let maxLat = -Infinity
  let matched = false
  for (const f of features) {
    if (String(f.properties.borough) !== borough) continue
    matched = true
    eachCoord(f.geometry, (lng, lat) => {
      minLng = Math.min(minLng, lng)
      minLat = Math.min(minLat, lat)
      maxLng = Math.max(maxLng, lng)
      maxLat = Math.max(maxLat, lat)
    })
  }
  if (!matched) return null
  return {
    longitude: (minLng + maxLng) / 2,
    latitude: (minLat + maxLat) / 2,
    zoom: 11.5,
    minZoom: CITY_VIEWS[city].minZoom,
    maxZoom: CITY_VIEWS[city].maxZoom,
  }
}

interface CrimeMapProps {
  boundaries?: BoundaryCollection
  map?: MapResponse
  level: Level
  borough: string
  metricLabel: string
  theme: Theme
  meta?: MetaResponse
}

export default function CrimeMap({
  boundaries,
  map,
  level,
  borough,
  metricLabel,
  theme,
  meta,
}: CrimeMapProps) {
  const city = meta?.city ?? CITIES[0]

  const [viewState, setViewState] = useState<ViewState>(CITY_VIEWS[CITIES[0].toLowerCase()])
  const idProp = ID_PROP[level]
  const values = map?.values ?? {}
  const counts = map?.crime_counts ?? {}
  const vmin = map?.vmin ?? 0
  const vmax = map?.vmax ?? 1

  const allowedBoroughs = useMemo(
    () => new Set(meta?.boroughs ?? []),
    [meta?.boroughs.join('\x00'), city]
  )

  const filteredBoundaries = useMemo<BoundaryCollection | null>(() => {
    if (!boundaries) return null
    if (!allowedBoroughs.size) return null

    const features = boundaries.features.filter(f =>
      allowedBoroughs.has(f.properties.borough as string)
    )
    return { ...boundaries, features }
  }, [boundaries, allowedBoroughs, city])

  // Refit to the selected borough (or back to London) when it changes.
  useEffect(() => {
    if (borough === 'All boroughs' || !filteredBoundaries) {
      setViewState(CITY_VIEWS[city.toLowerCase()])
      return
    }
    const next = boroughView(filteredBoundaries.features, borough, city)
    if (next) setViewState(next)
  }, [borough, filteredBoundaries])

  const layers = useMemo(() => {
    if (!filteredBoundaries) return []
    return [
      new GeoJsonLayer<BoundaryProps>({
        id: `crime-${level}`,
        data: filteredBoundaries,
        pickable: true,
        stroked: true,
        filled: true,
        getFillColor: (f: BoundaryFeature): RGBA =>
          rgbaForValue(values[String(f.properties[idProp])], vmin, vmax),
        getLineColor: LINE_COLOR[theme],
        lineWidthMinPixels: 0.4,
        updateTriggers: { getFillColor: [values, vmin, vmax, idProp], getLineColor: [theme] },
      }),
    ]
  }, [filteredBoundaries, values, vmin, vmax, idProp, level, theme, city])

  return (
    <DeckGL
      viewState={viewState}
      controller={{ dragRotate: false }}
      onViewStateChange={({ viewState: vs }) => setViewState(vs as unknown as ViewState)}
      layers={layers}
      getTooltip={({ object }: { object?: BoundaryFeature }) => {
        if (!object) return null
        const props = object.properties
        const id = String(props[idProp])
        const value = values[id]
        const count = counts[id] ?? 0
        const rows: string[] = []
        if (level === 'lsoa') rows.push(`<b>LSOA:</b> ${props.lsoa_name ?? id}`)
        if (level === 'ward') rows.push(`<b>Ward:</b> ${props.ward_name ?? id}`)
        rows.push(`<b>Borough:</b> ${props.borough ?? (level === 'borough' ? id : '')}`)
        rows.push(`<b>Crime count:</b> ${Math.round(count).toLocaleString()}`)
        rows.push(
          `<b>${metricLabel}:</b> ${
            value === undefined
              ? '—'
              : value.toLocaleString(undefined, { maximumFractionDigits: 1 })
          }`,
        )
        return {
          html: rows.join('<br/>'),
          style: {
            ...TOOLTIP_STYLE[theme],
            fontSize: '12px',
            padding: '8px 10px',
            borderRadius: '8px',
            boxShadow: '0 4px 14px rgba(0,0,0,0.25)',
          },
        }
      }}
    >
      <Map reuseMaps mapStyle={BASEMAP[theme]} />
    </DeckGL>
  )
}
