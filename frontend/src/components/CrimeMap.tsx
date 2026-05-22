import { useEffect, useMemo, useState } from 'react'
import DeckGL from '@deck.gl/react'
import { GeoJsonLayer } from '@deck.gl/layers'
import { Map } from 'react-map-gl/maplibre'
import type { Feature, Geometry } from 'geojson'
import { rgbaForValue, type RGBA } from '../lib/colors'
import type { BoundaryCollection, BoundaryProps, Level, MapResponse } from '../lib/types'
import type { Theme } from '../hooks/useTheme'

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

const LONDON_VIEW = { longitude: -0.1278, latitude: 51.5074, zoom: 9.2, minZoom: 9, maxZoom: 16 }

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
function boroughView(features: BoundaryFeature[], borough: string): ViewState | null {
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
    minZoom: LONDON_VIEW.minZoom,
    maxZoom: LONDON_VIEW.maxZoom,
  }
}

interface CrimeMapProps {
  boundaries?: BoundaryCollection
  map?: MapResponse
  level: Level
  borough: string
  metricLabel: string
  theme: Theme
}

export default function CrimeMap({
  boundaries,
  map,
  level,
  borough,
  metricLabel,
  theme,
}: CrimeMapProps) {
  const [viewState, setViewState] = useState<ViewState>(LONDON_VIEW)
  const idProp = ID_PROP[level]
  const values = map?.values ?? {}
  const counts = map?.crime_counts ?? {}
  const vmin = map?.vmin ?? 0
  const vmax = map?.vmax ?? 1

  // Refit to the selected borough (or back to London) when it changes.
  useEffect(() => {
    if (borough === 'All boroughs' || !boundaries) {
      setViewState(LONDON_VIEW)
      return
    }
    const next = boroughView(boundaries.features, borough)
    if (next) setViewState(next)
  }, [borough, boundaries])

  const layers = useMemo(() => {
    if (!boundaries) return []
    return [
      new GeoJsonLayer<BoundaryProps>({
        id: `crime-${level}`,
        data: boundaries,
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
  }, [boundaries, values, vmin, vmax, idProp, level, theme])

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
