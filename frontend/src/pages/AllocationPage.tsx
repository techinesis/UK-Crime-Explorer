import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchAllocation, fetchMeta } from '../lib/api'
import { useTheme } from '../hooks/useTheme'
import { BOROUGH_ALL, CITIES } from '../hooks/useFilters'
import ThemeToggle from '../components/ThemeToggle'
import type { AllocationEntry } from '../lib/types'
import type { Theme } from '../hooks/useTheme'

export const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const
const MODELS = [
  { value: 'lp', label: 'LP Optimisation' },
  { value: 'rawls', label: 'Rawls LP Optimisation' },
  { value: 'baseline', label: 'Proportional baseline' },
]

export function formatHour(h: number): string {
  if (h === 0) return '12am'
  if (h === 12) return '12pm'
  return h < 12 ? `${h}am` : `${h - 12}pm`
}

export function lerpRgb(from: [number, number, number], to: [number, number, number], t: number): string {
  const lerp = (x: number, y: number) => x + (y - x) * t
  const r = Math.round(lerp(from[0], to[0]))
  const g = Math.round(lerp(from[1], to[1]))
  const b = Math.round(lerp(from[2], to[2]))
  return `rgb(${r},${g},${b})`
}

export const CELL_LOW: Record<Theme, [number, number, number]> = {
  light: [241, 245, 249],
  dark: [15, 23, 42],
}
export const CELL_HIGH: Record<Theme, [number, number, number]> = {
  light: [29, 78, 216],
  dark: [245, 158, 11],
}

function aggregateSchedules(entries: AllocationEntry[]): number[][] {
  const result = Array.from({ length: 7 }, () => Array(24).fill(0))
  for (const e of entries) {
    for (let d = 0; d < 7; d++) {
      for (let h = 0; h < 24; h++) {
        result[d][h] += e.schedule[d]?.[h] ?? 0
      }
    }
  }
  return result
}

function peakDay(schedule: number[][]): string {
  const totals = schedule.map((row) => row.reduce((a, v) => a + v, 0))
  return DAYS[totals.indexOf(Math.max(...totals))]
}

function peakHour(schedule: number[][]): string {
  const totals = Array.from({ length: 24 }, (_, h) =>
    schedule.reduce((s, row) => s + (row[h] ?? 0), 0),
  )
  return formatHour(totals.indexOf(Math.max(...totals)))
}

interface HeatmapProps {
  schedule: number[][] // [day][hour]
  theme: Theme
  label?: string
}

const DAY_LABEL_W = 36
const BLOCK_HOURS = [0, 6, 12, 18]
const BLOCK_LABELS: Record<number, string> = { 0: 'Midnight', 6: '6am', 12: 'Noon', 18: '6pm' }

function WeeklyHeatmap({ schedule, theme, label }: HeatmapProps) {
  const maxVal = Math.max(...schedule.flat(), 1)
  const cellBg = (v: number) => lerpRgb(CELL_LOW[theme], CELL_HIGH[theme], v / maxVal)
  const isLight = theme === 'light'
  const divider = isLight ? 'rgba(100,116,139,0.2)' : 'rgba(148,163,184,0.15)'
  const cellRing = isLight ? '0 0 0 1px rgba(0,0,0,0.07)' : '0 0 0 1px rgba(255,255,255,0.05)'

  return (
    <div>
      {label && <p className="mb-3 text-xs text-muted">{label}</p>}

      <div style={{ display: 'flex', paddingLeft: DAY_LABEL_W, marginBottom: 2 }}>
        {BLOCK_HOURS.map((h, i) => (
          <div key={h} style={{ flex: 6, borderLeft: i > 0 ? `1px solid ${divider}` : undefined, paddingLeft: i > 0 ? 4 : 0 }}>
            <span style={{ fontSize: 9, color: '#64748b', fontWeight: 600 }}>{BLOCK_LABELS[h]}</span>
          </div>
        ))}
      </div>

      {schedule.slice(0, 7).map((row, d) => (
        <div
          key={d}
          style={{
            display: 'flex',
            alignItems: 'stretch',
            marginBottom: d === 4 ? 8 : 2,
          }}
        >
          <div
            style={{
              width: DAY_LABEL_W,
              flexShrink: 0,
              fontSize: 11,
              fontWeight: d >= 5 ? 700 : 400,
              color: d >= 5 ? (isLight ? '#2563eb' : '#f59e0b') : '#64748b',
              textAlign: 'right',
              paddingRight: 8,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'flex-end',
            }}
          >
            {DAYS[d]}
          </div>

          {BLOCK_HOURS.map((blockStart, bi) => (
            <div
              key={blockStart}
              style={{
                flex: 6,
                display: 'grid',
                gridTemplateColumns: 'repeat(6, 1fr)',
                columnGap: 2,
                borderLeft: bi > 0 ? `1px solid ${divider}` : undefined,
                paddingLeft: bi > 0 ? 4 : 0,
              }}
            >
              {row.slice(blockStart, blockStart + 6).map((val, offset) => {
                const h = blockStart + offset
                return (
                  <div
                    key={h}
                    title={`${DAYS[d]} ${formatHour(h)}–${formatHour((h + 1) % 24)}: ${Math.round(val)} unit-hrs`}
                    style={{
                      aspectRatio: '1',
                      borderRadius: 3,
                      backgroundColor: cellBg(val),
                      boxShadow: cellRing,
                      cursor: 'default',
                    }}
                  />
                )
              })}
            </div>
          ))}
        </div>
      ))}

      {/* Legend */}
      <div className="mt-4 flex items-center gap-2 text-xs text-muted">
        <span>Low</span>
        <div
          style={{
            height: 8,
            flex: 1,
            borderRadius: 4,
            background: `linear-gradient(to right, ${lerpRgb(CELL_LOW[theme], CELL_HIGH[theme], 0)}, ${lerpRgb(CELL_LOW[theme], CELL_HIGH[theme], 1)})`,
          }}
        />
        <span>High</span>
      </div>
    </div>
  )
}

const selectClass =
  'rounded-md border border-border bg-card px-3 py-1.5 text-sm text-fg focus:border-accent focus:outline-none'

export default function AllocationPage() {
  const { theme, toggle } = useTheme()
  const city = CITIES[0]
  const [borough, setBorough] = useState(BOROUGH_ALL)
  const [totalUnits, setTotalUnits] = useState(33000)
  const [model, setModel] = useState(MODELS[0].value)
  const [inputUnits, setInputUnits] = useState('33000')

  const meta = useQuery({
    queryKey: ['meta', city],
    queryFn: () => fetchMeta(city),
  })

  const allocation = useQuery({
    queryKey: ['allocation', city, totalUnits, model],
    queryFn: () => fetchAllocation(city, totalUnits, model),
    staleTime: Infinity,
  })

  const boroughs = meta.data?.boroughs ?? []

  const filteredEntries = useMemo(() => {
    const entries = allocation.data?.entries ?? []
    if (borough === BOROUGH_ALL) return entries
    return entries.filter((e) => e.borough === borough)
  }, [allocation.data, borough])

  const aggregated = useMemo(
    () => (filteredEntries.length ? aggregateSchedules(filteredEntries) : null),
    [filteredEntries],
  )

  const boroughBreakdown = useMemo(() => {
    const entries = allocation.data?.entries ?? []
    const totals = new Map<string, number>()
    for (const e of entries) {
      totals.set(e.borough, (totals.get(e.borough) ?? 0) + e.units)
    }
    return [...totals.entries()]
      .map(([b, total]) => ({ borough: b, total }))
      .sort((a, b) => b.total - a.total)
  }, [allocation.data])

  const maxBoroughTotal = Math.max(...boroughBreakdown.map((b) => b.total), 1)

  const topLsoas = useMemo(
    () =>
      [...filteredEntries]
        .sort((a, b) => b.units - a.units)
        .slice(0, 20)
        .map((e) => ({
          ...e,
          weeklyHours: e.schedule.flat().reduce((s, v) => s + v, 0),
          peakDay: peakDay(e.schedule),
          peakHour: peakHour(e.schedule),
        })),
    [filteredEntries],
  )

  const totalWeeklyHours = filteredEntries.reduce(
    (s, e) => s + e.schedule.flat().reduce((a, v) => a + v, 0),
    0,
  )
  const coveredLsoas = filteredEntries.filter((e) =>
    e.schedule.flat().some((v) => v > 0),
  ).length
  const pDay = aggregated ? peakDay(aggregated) : '&mdash;'
  const pHour = aggregated ? peakHour(aggregated) : '&mdash;'

  const loading = allocation.isLoading
  const noData = !loading && !allocation.data

  function commitUnits() {
    const v = parseInt(inputUnits, 10)
    if (Number.isFinite(v) && v > 0) setTotalUnits(v)
  }

  return (
    <div className="h-full overflow-y-auto bg-surface">
      <div className="mx-auto max-w-7xl px-5 py-6">
        {/* Header */}
        <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold text-fg">Police Unit Allocation</h1>
            <p className="mt-1 text-sm text-muted">
              Recommended deployment of{' '}
              <span className="font-medium text-fg">{totalUnits.toLocaleString()} units</span>{' '}
              across {city} &mdash; optimised by crime severity, volume, and equity.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {/* Borough */}
            <select
              className={selectClass}
              value={borough}
              onChange={(e) => setBorough(e.target.value)}
            >
              <option value={BOROUGH_ALL}>{BOROUGH_ALL}</option>
              {boroughs.map((b) => (
                <option key={b} value={b}>
                  {b}
                </option>
              ))}
            </select>

            {/* Model */}
            <select
              className={selectClass}
              value={model}
              onChange={(e) => setModel(e.target.value)}
            >
              {MODELS.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>

            {/* Total units */}
            <div className="flex items-center gap-1">
              <label className="text-xs text-muted">Units</label>
              <input
                type="number"
                min={100}
                max={50000}
                step={100}
                value={inputUnits}
                onChange={(e) => setInputUnits(e.target.value)}
                onBlur={commitUnits}
                onKeyDown={(e) => e.key === 'Enter' && commitUnits()}
                className="w-24 rounded-md border border-border bg-card px-2 py-1.5 text-sm text-fg focus:border-accent focus:outline-none"
              />
            </div>

            <ThemeToggle theme={theme} onToggle={toggle} />
          </div>
        </div>

        {loading && (
          <div className="py-16 text-center">
            <p className="text-sm text-muted">Computing allocation…</p>
            <p className="mt-1 text-xs text-muted">
              First load runs the LP model &mdash; this can take a few seconds.
            </p>
          </div>
        )}

        {allocation.isError && (
          <div className="rounded-lg border border-red-500/30 bg-red-900/10 p-6 text-center">
            <p className="text-sm text-red-400">
              {(allocation.error as Error)?.message ?? 'Failed to load allocation data.'}
            </p>
          </div>
        )}

        {noData && !allocation.isError && (
          <div className="rounded-lg border border-border bg-card p-8 text-center">
            <p className="text-muted">No allocation data returned for {city}.</p>
          </div>
        )}

        {allocation.data?.warning && (
          <div className="mb-5 rounded-lg border border-yellow-500/30 bg-yellow-900/10 p-4">
            <p className="text-sm font-medium text-yellow-400">LP optimisation failed</p>
            <p className="mt-0.5 text-xs text-yellow-400/80">{allocation.data.warning}</p>
          </div>
        )}

        {!allocation.data?.warning && aggregated && (
          <>
            {/* Summary */}
            <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[
                {
                  label: 'Weekly unit-hours',
                  value: Math.round(totalWeeklyHours).toLocaleString(),
                  sub:
                    borough !== BOROUGH_ALL ? borough : `across ${city}`,
                },
                {
                  label: 'LSOAs with allocation',
                  value: coveredLsoas.toLocaleString(),
                  sub: `of ${filteredEntries.length} total`,
                },
                { label: 'Busiest day', value: pDay, sub: 'highest total deployment' },
                { label: 'Peak hour', value: pHour, sub: 'most units simultaneously' },
              ].map((s) => (
                <div key={s.label} className="rounded-lg border border-border bg-card p-4">
                  <p className="text-[10px] font-semibold uppercase tracking-widest text-muted">
                    {s.label}
                  </p>
                  <p className="mt-1 text-2xl font-bold tabular-nums text-fg">{s.value}</p>
                  <p className="mt-0.5 text-[11px] text-muted">{s.sub}</p>
                </div>
              ))}
            </div>

            {/* Heatmap and Borough breakdown */}
            <div className="mb-5 grid gap-4 lg:grid-cols-[1fr_320px]">
              <div className="rounded-lg border border-border bg-card p-5">
                <div className="mb-3 flex items-center justify-between">
                  <h2 className="text-sm font-semibold text-fg">
                    Weekly deployment schedule
                    {borough !== BOROUGH_ALL && (
                      <span className="ml-2 font-normal text-muted">&mdash; {borough}</span>
                    )}
                  </h2>
                </div>
                <div className="px-6">
                  <WeeklyHeatmap
                    schedule={aggregated}
                    theme={theme}
                    label={`Aggregated unit-hours per time slot across ${borough === BOROUGH_ALL ? 'all areas' : borough}. Darker = more units deployed. Hover for exact count.`}
                  />
                </div>
              </div>

              <div className="rounded-lg border border-border bg-card p-5">
                <h2 className="mb-1 text-sm font-semibold text-fg">Borough breakdown</h2>
                <p className="mb-3 text-xs text-muted">
                  Total allocated units. Click to filter.
                </p>
                <div className="space-y-2 overflow-y-auto" style={{ maxHeight: 380 }}>
                  {boroughBreakdown.map(({ borough: b, total }) => {
                    const active = borough === b
                    return (
                      <button
                        key={b}
                        onClick={() => setBorough(active ? BOROUGH_ALL : b)}
                        className="w-full text-left"
                      >
                        <div className="flex items-center justify-between text-xs">
                          <span
                            className={`font-medium ${active ? 'text-accent' : 'text-fg'} truncate pr-2`}
                          >
                            {b}
                          </span>
                          <span className="shrink-0 tabular-nums text-muted">
                            {Math.round(total).toLocaleString()}
                          </span>
                        </div>
                        <div className="mt-0.5 h-1.5 w-full overflow-hidden rounded-full bg-surface">
                          <div
                            className="h-full rounded-full bg-accent transition-all"
                            style={{
                              width: `${(total / maxBoroughTotal) * 100}%`,
                              opacity: active ? 1 : 0.55,
                            }}
                          />
                        </div>
                      </button>
                    )
                  })}
                  {boroughBreakdown.length === 0 && (
                    <p className="text-xs text-muted">No data.</p>
                  )}
                </div>
              </div>
            </div>

            {/* Top LSOAs */}
            <div className="rounded-lg border border-border bg-card p-5">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-semibold text-fg">
                  Top {topLsoas.length} highest-allocation LSOAs
                  {borough !== BOROUGH_ALL && (
                    <span className="ml-2 font-normal text-muted">&mdash; {borough}</span>
                  )}
                </h2>
                <span className="text-xs text-muted">
                  Sorted by total units allocated
                </span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-border text-left">
                      <th className="pb-2 pr-3 font-medium text-muted">#</th>
                      <th className="pb-2 pr-3 font-medium text-muted">LSOA</th>
                      <th className="pb-2 pr-3 font-medium text-muted">Borough</th>
                      <th className="pb-2 pr-3 text-right font-medium text-muted">
                        Units
                      </th>
                      <th className="pb-2 pr-3 text-right font-medium text-muted">
                        Weekly hrs
                      </th>
                      <th className="pb-2 pr-3 font-medium text-muted">Busiest day</th>
                      <th className="pb-2 font-medium text-muted">Peak hour</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topLsoas.map((r, i) => (
                      <tr
                        key={r.lsoa_code}
                        className="border-b border-border/50 last:border-0 hover:bg-surface/60"
                      >
                        <td className="py-1.5 pr-3 text-muted">{i + 1}</td>
                        <td className="py-1.5 pr-3">
                          <div className="font-medium text-fg">{r.lsoa_name}</div>
                          <div className="text-[10px] text-muted">{r.lsoa_code}</div>
                        </td>
                        <td className="py-1.5 pr-3 text-muted">{r.borough}</td>
                        <td className="py-1.5 pr-3 text-right tabular-nums font-semibold text-accent">
                          {Math.round(r.units).toLocaleString()}
                        </td>
                        <td className="py-1.5 pr-3 text-right tabular-nums text-fg">
                          {r.weeklyHours.toLocaleString()}
                        </td>
                        <td className="py-1.5 pr-3 text-muted">{r.peakDay}</td>
                        <td className="py-1.5 text-muted">{r.peakHour}</td>
                      </tr>
                    ))}
                    {topLsoas.length === 0 && (
                      <tr>
                        <td colSpan={7} className="py-4 text-center text-muted">
                          No data for this selection.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <p className="mt-4 text-[11px] text-muted">
              <strong>LP model</strong> maximises severity-weighted
              crime coverage, raw crime volume, and crime-type diversity, subject to
              borough equity floors and per-LSOA min/max caps.<br/>
              <strong>Rawls LP model</strong> aims to favour the disadvantaged by balancing
              allocation more fairly across all LSOAs, however this may underestimate severity of
              certain high-volume areas.<br/>
              <strong>Baseline</strong> allocates proportionally to
              raw crime volume. Schedule shape is derived from empirical hourly and daily crime-type
              patterns.<br/>
              Provided suggestions are merely advisory. Decisions should be made by a human planner.
            </p>
          </>
        )}
      </div>
    </div>
  )
}
