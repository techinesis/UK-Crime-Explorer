import { useMemo } from 'react'
import type { Level, MapResponse } from '../lib/types'

interface SummaryStatsProps {
  level: Level
  map?: MapResponse
}

const UNIT_LABEL: Record<Level, { active: string; average: string }> = {
  lsoa: { active: 'LSOAs with crimes', average: 'Average per LSOA' },
  ward: { active: 'Wards with crimes', average: 'Average per ward' },
  borough: { active: 'Boroughs with crimes', average: 'Average per borough' },
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="text-[11px] uppercase tracking-wide text-muted">{label}</div>
      <div className="mt-0.5 text-lg font-semibold tabular-nums text-fg">{value}</div>
    </div>
  )
}

export default function SummaryStats({ level, map }: SummaryStatsProps) {
  const { total, active, average } = useMemo(() => {
    const counts = Object.values(map?.crime_counts ?? {})
    const sum = counts.reduce((a, b) => a + b, 0)
    return {
      total: sum,
      active: counts.filter((c) => c > 0).length,
      average: counts.length ? sum / counts.length : 0,
    }
  }, [map])

  const labels = UNIT_LABEL[level]
  return (
    <div className="grid grid-cols-3 gap-2">
      <Stat label="Total selected crimes" value={Math.round(total).toLocaleString()} />
      <Stat label={labels.active} value={active.toLocaleString()} />
      <Stat
        label={labels.average}
        value={average.toLocaleString(undefined, { maximumFractionDigits: 2 })}
      />
    </div>
  )
}
