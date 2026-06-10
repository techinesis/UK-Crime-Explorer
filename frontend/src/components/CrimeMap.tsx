import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import DeckGL from '@deck.gl/react'
import { GeoJsonLayer } from '@deck.gl/layers'
import { Map } from 'react-map-gl/maplibre'
import type { Feature, Geometry } from 'geojson'
import { rgbaForValue, type RGBA } from '../lib/colors'
import type { BoundaryCollection, BoundaryProps, Level, MapResponse, MetaResponse } from '../lib/types'
import type { Theme } from '../hooks/useTheme'
import { CITIES } from '../hooks/useFilters'
import type { PickingInfo } from '@deck.gl/core'

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

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const
const N_HOURS = 24

interface ViewState {
  longitude: number
  latitude: number
  zoom: number
  minZoom?: number
  maxZoom?: number
}

type BoundaryFeature = Feature<Geometry, BoundaryProps>

interface PopupState {
  lsoa: string
  name: string
  borough: string
  schedule: number[][] // [day][hour]
  x: number
  y: number
}

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

function formatHour(h: number): string {
  if (h === 0) return '12a'
  if (h === 12) return '12p'
  return h < 12 ? `${h}a` : `${h - 12}p`
}

function lerpRgb(from: [number, number, number], to: [number, number, number], t: number): string {
  const lerp = (x: number, y: number) => x + (y - x) * t
  const r = Math.round(lerp(from[0], to[0]))
  const g = Math.round(lerp(from[1], to[1]))
  const b = Math.round(lerp(from[2], to[2]))
  return `rgb(${r},${g},${b})`
}

const CELL_LOW:  Record<Theme, [number,number,number]> = {
  light: [241, 245, 249],
  dark:  [15, 23, 42],
}
const CELL_HIGH: Record<Theme, [number,number,number]> = {
  light: [29, 78, 216],
  dark:  [245, 158, 11],
}
interface SchedulePopupProps {
  popup: PopupState
  theme: Theme
  onClose: () => void
}

function SchedulePopup({ popup, theme, onClose }: SchedulePopupProps) {
  const popupRef = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState({ left: popup.x + 14, top: popup.y - 24 })

  useEffect(() => {
    const el = popupRef.current
    if (!el) return
    const parent = el.offsetParent as HTMLElement | null
    if (!parent) return
    const pw = parent.clientWidth, ph = parent.clientHeight
    const ew = el.offsetWidth, eh = el.offsetHeight

    let left = popup.x + 14, top = popup.y - 24
    if (left + ew > pw - 8) left = popup.x - ew - 14
    if (top + eh > ph - 8) top = ph - eh - 8
    if (top < 8) top = 8
    if (left < 8) left = 8
    setPos({ left, top })
  }, [popup.x, popup.y])

  const schedule = popup.schedule
  const allValues = schedule.flat()
  const maxVal = Math.max(...allValues, 1)
  const totalUnits = allValues.reduce((a, b) => a + b, 0)

  const dayTotals = schedule.map(row => row.reduce((a, b) => a + b, 0))
  const peakDay = DAYS[dayTotals.indexOf(Math.max(...dayTotals))]
  const hourTotals = Array.from({ length: N_HOURS }, (_, h) => schedule.reduce((s, row) => s + (row[h] ?? 0), 0))
  const peakHour = formatHour(hourTotals.indexOf(Math.max(...hourTotals)))

  const cellBg = (val: number) => lerpRgb(CELL_LOW[theme], CELL_HIGH[theme], val / maxVal)

  const isLight = theme === 'light'
  const surface = isLight ? 'rgba(255,255,255,0.97)' : 'rgba(15,23,42,0.97)'
  const border = isLight ? 'rgba(148,163,184,0.35)' : 'rgba(255,255,255,0.08)'
  const text = isLight ? '#0f172a' : '#f1f5f9'
  const muted = '#64748b'
  const hairline = isLight ? '#e2e8f0' : '#1e293b'

  const rowBg = (d: number): string => {
    if (d < 5) return 'transparent'
    return isLight ? 'rgba(248,250,252,0.9)' : 'rgba(30,41,59,0.6)'
  }

  /* NOTE: LLM used to help with styling these elements */
  return (
    <div
      ref={popupRef}
      style={{
        position: 'absolute',
        left: pos.left,
        top: pos.top,
        background: surface,
        color: text,
        borderRadius: 14,
        boxShadow: isLight ? '0 8px 32px rgba(0,0,0,0.18), 0 1px 4px rgba(0,0,0,0.08)'
                           : '0 8px 32px rgba(0,0,0,0.6), 0 1px 4px rgba(0,0,0,0.3)',
        border: `1px solid ${border}`,
        padding: '14px 16px 12px',
        width: 492,
        fontSize: 12,
        userSelect: 'none',
        backdropFilter: 'blur(12px)',
      }}
    >
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'flex-start',
        marginBottom: 10,
      }}>
        {/* Title */}
        <div>
          <div style={{ fontWeight: 700, fontSize: 14, letterSpacing: '-0.01em' }}>{popup.name}</div>
          <div style={{ color: muted, marginTop: 2, fontSize: 11 }}>
            {popup.borough}&ensp;&middot;&ensp;<span style={{ fontVariantNumeric: 'tabular-nums' }}>{popup.lsoa}</span>
          </div>
        </div>
        <button
          onClick={onClose}
          aria-label="Close"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: 22,
            height: 22,
            marginTop: -2,
            marginLeft: 8,
            borderRadius: '50%',
            cursor: 'pointer',
            background: isLight ? '#f1f5f9' : '#1e293b',
            border: 'none',
            color: muted,
            fontSize: 15,
            lineHeight: 1,
          }}
        >
          &times;
        </button>
      </div>

      {/* Stats */}
      <div style={{
        display: 'flex',
        gap: 0,
        marginBottom: 12,
        paddingBottom: 11,
        borderBottom: `1px solid ${hairline}`,
      }}>
        {[
          { label: 'Weekly units', value: Math.round(totalUnits).toLocaleString() },
          { label: 'Busiest day', value: peakDay },
          { label: 'Busiest hour', value: peakHour },
        ].map((s, i, arr) => (
          <div key={s.label} style={{
            flex: 1,
            paddingLeft: i > 0 ? 12 : 0,
            paddingRight: i < arr.length - 1 ? 12 : 0,
            borderRight: i < arr.length - 1 ? `1px solid ${hairline}` : 'none',
          }}>
            <div style={{ color: muted, fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 3 }}>
              {s.label}
            </div>
            <div style={{ fontWeight: 700, fontSize: 15, fontVariantNumeric: 'tabular-nums', letterSpacing: '-0.02em' }}>
              {s.value}
            </div>
          </div>
        ))}
      </div>

      {/* Heatmap */}
      <div>
        <div style={{ display: 'flex', marginLeft: 30, marginBottom: 3 }}>
          {Array.from({ length: N_HOURS }, (_, h) => (
            <div key={h} style={{
              width: 18, flexShrink: 0, textAlign: 'center',
              color: muted, fontSize: 9, fontVariantNumeric: 'tabular-nums',
              opacity: h % 6 == 0 ? 1 : 0, pointerEvents: 'none',
            }}>
              {formatHour(h)}
            </div>
          ))}
        </div>

        {schedule.slice(0, 7).map((row, d) => (
          <div
            key={d}
            style={{
              display: 'flex',
              alignItems: 'center',
              marginBottom: d === 4 ? 3 : 1.5,
              paddingLeft: 2,
              paddingRight: 2,
              paddingTop: 1,
              paddingBottom: 1,
              borderRadius: 4,
              background: rowBg(d),
            }}
          >
            <div style={{
              width: 26,
              flexShrink: 0,
              color: d >= 5 ? (isLight ? '#3b82f6' : '#f59e0b') : muted,
              fontSize: 10,
              fontWeight: d >= 5 ? 600 : 400,
              textAlign: 'right',
              paddingRight: 5,
              letterSpacing: '0.02em',
            }}>
              {DAYS[d]}
            </div>

          {Array.from({ length: N_HOURS }, (_, h) => {
            const val = row[h] ?? 0
            return (
              <div
                key={h}
                title={`${DAYS[d]} ${formatHour(h)}-${formatHour(h + 1 < 24 ? h + 1 : 0)}: ${val} units`}
                style={{
                  width: 16,
                  height: 14,
                  flexShrink: 0,
                  margin: '0 1px',
                  borderRadius: 3,
                  backgroundColor: cellBg(val),
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  cursor: 'default',
                  transition: 'transform 80ms',
                }}
              />
            )
          })}
          </div>
        ))}
      </div>
    </div>
  )
}

interface CrimeMapProps {
  boundaries?: BoundaryCollection
  map?: MapResponse
  level: Level
  borough: string
  isForecast: boolean
  metricLabel: string
  theme: Theme
  meta?: MetaResponse
}

export default function CrimeMap({
  boundaries,
  map,
  level,
  borough,
  isForecast,
  metricLabel,
  theme,
  meta,
}: CrimeMapProps) {
  const city = meta?.city ?? CITIES[0]

  const [viewState, setViewState] = useState<ViewState>(CITY_VIEWS[CITIES[0].toLowerCase()])
  const [popup, setPopup] = useState<PopupState | null>(null)

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

  const displaySchedule = useCallback((info: PickingInfo) => {
    if (!info.object || level !== 'lsoa' || !isForecast) {
      setPopup(null)
      return
    }

    const feature = info.object as BoundaryFeature
    const props = feature.properties
    const lsoa = String(props.lsoa_code)
    // const schedule = meta?.schedule?.[lsoa]
    // Temporary hardcoded schedule:
    const schedule = [
      [1, 1, 0, 0, 0, 1, 2, 3, 4, 5, 5, 5, 4, 4, 4, 5, 6, 7, 8, 9, 8, 6, 4, 2],
      [1, 0, 0, 0, 0, 1, 2, 3, 4, 5, 5, 5, 4, 4, 4, 5, 6, 7, 8, 8, 7, 5, 3, 2],
      [1, 1, 0, 0, 0, 1, 2, 3, 4, 5, 5, 5, 4, 4, 4, 5, 6, 7, 9, 9, 8, 6, 4, 2],
      [2, 1, 0, 0, 0, 1, 2, 3, 4, 5, 5, 5, 4, 4, 5, 5, 7, 8, 9, 10, 9, 7, 5, 3],
      [3, 2, 1, 0, 0, 1, 2, 3, 4, 5, 5, 5, 4, 4, 5, 6, 8, 9, 11, 13, 14, 12, 9, 6],
      [5, 4, 3, 2, 1, 1, 2, 2, 3, 4, 4, 4, 4, 4, 5, 6, 8, 10, 12, 14, 15, 14, 11, 8],
      [4, 3, 2, 1, 0, 1, 1, 2, 3, 3, 4, 4, 4, 3, 3, 4, 5, 6, 7, 8, 7, 5, 4, 3],
    ]

    if (!schedule) {
      setPopup(null)
      return
    }

    setPopup({
      lsoa,
      name: String(props.lsoa_name ?? lsoa),
      borough: String(props.borough ?? ''),
      schedule,
      x: info.x,
      y: info.y,
    })
  }, [meta?.schedule, level, isForecast])

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      <DeckGL
        viewState={viewState}
        controller={{ dragRotate: false }}
        onViewStateChange={({ viewState: vs }) => setViewState(vs as unknown as ViewState)}
        layers={layers}
        onClick={displaySchedule}
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

      {popup && (
        <SchedulePopup
          popup={popup}
          theme={theme}
          onClose={() => setPopup(null)}
        />
      )}
    </div>
  )
}
