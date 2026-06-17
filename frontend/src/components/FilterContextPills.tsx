// A read-only pill bar that mirrors the dashboard filters the chat is reasoning
// about, shown just above the chat input so the user always has visual confirmation
// of the assistant's context. Reads the same `filters` the chat already receives —
// no new state. Up to five pills; flex-wrap drops them to a second line on narrow
// (sub-480px) panel widths.

import { BOROUGH_ALL, CITIES, DEFAULT_FILTERS, LEVEL_OPTIONS } from '../hooks/useFilters'
import type { FilterState } from '../hooks/useFilters'

const MONTH_ABBR = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
]

function categoryLabel(categories: string[]): string {
  if (categories.length === 0) return 'All categories'
  if (categories.length === 1) return categories[0]
  return `${categories.length} categories`
}

function timeLabel(year: number | null, months: number[]): string {
  if (year === null && months.length === 0) return 'All time'
  const parts: string[] = [year === null ? 'All years' : String(year)]
  if (months.length > 0 && months.length < 12) {
    const sorted = [...months].sort((a, b) => a - b)
    const names = sorted.map((m) => MONTH_ABBR[m - 1] ?? String(m))
    parts.push(names.length <= 3 ? names.join(', ') : `${months.length} months`)
  }
  return parts.join(' · ')
}

interface Pill {
  key: string
  prefix: string
  value: string
}

interface FilterContextPillsProps {
  filters: FilterState
}

export default function FilterContextPills({ filters }: FilterContextPillsProps) {
  const levelLabel =
    LEVEL_OPTIONS.find((l) => l.value === filters.level)?.label ?? String(filters.level)

  const pills: Pill[] = []
  // City only shows when it differs from the default — London is the implied baseline.
  if (filters.city !== DEFAULT_FILTERS.city && filters.city !== CITIES[0]) {
    pills.push({ key: 'city', prefix: 'city', value: filters.city })
  }
  pills.push({ key: 'category', prefix: 'category', value: categoryLabel(filters.categories) })
  pills.push({ key: 'borough', prefix: 'borough', value: filters.borough || BOROUGH_ALL })
  pills.push({ key: 'time', prefix: 'when', value: timeLabel(filters.year, filters.months) })
  pills.push({ key: 'level', prefix: 'level', value: levelLabel })

  return (
    <div className="flex flex-wrap gap-1 border-t border-border px-3 py-2" aria-label="Active filters">
      {pills.map((p) => (
        <span
          key={p.key}
          className="flex items-center gap-1 rounded-full bg-card px-2 py-0.5 text-[10px] text-muted"
        >
          <span className="text-[9px] uppercase tracking-wide opacity-70">{p.prefix}</span>
          <span className="text-fg">{p.value}</span>
        </span>
      ))}
    </div>
  )
}
