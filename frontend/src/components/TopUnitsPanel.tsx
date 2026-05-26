import { useMemo } from 'react'
import type { BoundaryCollection, Level, MapResponse } from '../lib/types'

interface TopUnitsPanelProps {
  level: Level
  boundaries?: BoundaryCollection
  map?: MapResponse
  metricLabel: string
}

const LEVEL_LABEL: Record<Level, string> = { lsoa: 'LSOAs', ward: 'Wards', borough: 'Boroughs' }

function nameFor(level: Level, props: Record<string, string | number | null>, id: string): string {
  if (level === 'lsoa') return String(props.lsoa_name ?? id)
  if (level === 'ward') return String(props.ward_name ?? id)
  return id
}

export default function TopUnitsPanel({ level, boundaries, map, metricLabel }: TopUnitsPanelProps) {
  const rows = useMemo(() => {
    if (!boundaries || !map) return []
    const idProp = level === 'lsoa' ? 'lsoa_code' : level === 'ward' ? 'ward_code' : 'borough'
    const info = new Map<string, { name: string; borough: string }>()
    for (const f of boundaries.features) {
      const id = String(f.properties[idProp])
      if (!info.has(id)) {
        info.set(id, { name: nameFor(level, f.properties, id), borough: String(f.properties.borough ?? '') })
      }
    }
    return Object.entries(map.values)
      .map(([id, value]) => ({
        id,
        value,
        count: map.crime_counts[id] ?? 0,
        name: info.get(id)?.name ?? id,
        borough: info.get(id)?.borough ?? '',
      }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 10)
  }, [boundaries, map, level])

  return (
    <section className="rounded-lg border border-border bg-card p-3">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
        Top 10 {LEVEL_LABEL[level]} — {metricLabel}
      </h3>
      <table className="w-full text-xs text-fg">
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.id} className="border-b border-border/60 last:border-0">
              <td className="py-1 pr-2 text-muted">{i + 1}</td>
              <td className="py-1 pr-2">
                <div className="font-medium text-fg">{r.name}</div>
                {level !== 'borough' && <div className="text-[10px] text-muted">{r.borough}</div>}
              </td>
              <td className="py-1 text-right tabular-nums text-accent">
                {r.value.toLocaleString(undefined, { maximumFractionDigits: 1 })}
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td className="py-2 text-muted">No data for this selection.</td>
            </tr>
          )}
        </tbody>
      </table>
    </section>
  )
}
