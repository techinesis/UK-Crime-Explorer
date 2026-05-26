import type { MetaResponse } from '../lib/types'
import {
  BOROUGH_ALL,
  LEVEL_OPTIONS,
  METRIC_OPTIONS,
  TIER_ALL,
  YEAR_ALL,
  type FilterState,
} from '../hooks/useFilters'

const CONFIDENCE_EMOJI: Record<string, string> = { High: '🟢', Medium: '🟡', Low: '🔴' }

const selectClass =
  'w-full rounded-md border border-border bg-card px-2 py-1.5 text-sm text-fg focus:border-accent focus:outline-none'

function toggleClass(active: boolean): string {
  return `flex-1 rounded-md border px-2 py-1 text-sm ${
    active ? 'border-accent bg-accent/15 text-fg' : 'border-border bg-card text-muted'
  }`
}

interface SidebarProps {
  meta?: MetaResponse
  filters: FilterState
  update: (patch: Partial<FilterState>) => void
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="mb-1.5 mt-4 text-xs font-semibold uppercase tracking-wide text-muted">
      {children}
    </h3>
  )
}

export default function Sidebar({ meta, filters, update }: SidebarProps) {
  const confidenceByCategory = new Map(
    (meta?.categories ?? []).map((c) => [c.name, c.preventability_confidence]),
  )

  const toggleCategory = (name: string) => {
    const set = new Set(filters.categories)
    if (set.has(name)) set.delete(name)
    else set.add(name)
    update({ categories: [...set] })
  }

  const toggleMonth = (m: number) => {
    const set = new Set(filters.months)
    if (set.has(m)) set.delete(m)
    else set.add(m)
    update({ months: [...set].sort((a, b) => a - b) })
  }

  return (
    <div className="space-y-1 text-fg">
      <SectionTitle>Map mode</SectionTitle>
      <select
        className={selectClass}
        value={filters.metric}
        onChange={(e) => update({ metric: e.target.value as FilterState['metric'] })}
      >
        {METRIC_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>

      <SectionTitle>Severity basis</SectionTitle>
      <div className="flex gap-2">
        {(['mean', 'median'] as const).map((b) => (
          <button
            key={b}
            type="button"
            onClick={() => update({ severityBasis: b })}
            className={toggleClass(filters.severityBasis === b)}
          >
            {b === 'mean' ? 'Mean CCHI' : 'Median CCHI'}
          </button>
        ))}
      </div>

      <SectionTitle>Aggregation level</SectionTitle>
      <div className="flex gap-2">
        {LEVEL_OPTIONS.map((o) => (
          <button
            key={o.value}
            type="button"
            onClick={() => update({ level: o.value })}
            className={toggleClass(filters.level === o.value)}
          >
            {o.label}
          </button>
        ))}
      </div>

      <SectionTitle>Crime type</SectionTitle>
      <p className="mb-1 text-[11px] text-muted">
        🟢/🟡/🔴 = preventability evidence strength. Empty = all.
      </p>
      <div className="max-h-44 space-y-0.5 overflow-y-auto rounded-md border border-border bg-card p-2">
        {(meta?.categories ?? []).map((c) => {
          const emoji = CONFIDENCE_EMOJI[confidenceByCategory.get(c.name) ?? 'Low'] ?? '⚪'
          const checked = filters.categories.includes(c.name)
          return (
            <label key={c.name} className="flex cursor-pointer items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={checked}
                onChange={() => toggleCategory(c.name)}
                className="accent-accent"
              />
              <span>
                {emoji} {c.name}
              </span>
            </label>
          )
        })}
      </div>

      <SectionTitle>Preventability tier</SectionTitle>
      <select
        className={selectClass}
        value={filters.tier}
        onChange={(e) => update({ tier: e.target.value })}
      >
        {[TIER_ALL, 'High', 'Medium', 'Low'].map((t) => (
          <option key={t} value={t}>
            {t}
          </option>
        ))}
      </select>

      <SectionTitle>Year</SectionTitle>
      <select
        className={selectClass}
        value={filters.year === null ? YEAR_ALL : String(filters.year)}
        onChange={(e) => update({ year: e.target.value === YEAR_ALL ? null : Number(e.target.value) })}
      >
        <option value={YEAR_ALL}>{YEAR_ALL}</option>
        {(meta?.years ?? []).map((y) => (
          <option key={y} value={y}>
            {y}
          </option>
        ))}
      </select>

      <SectionTitle>Months</SectionTitle>
      <div className="grid grid-cols-6 gap-1">
        {(meta?.months ?? []).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => toggleMonth(m)}
            className={`rounded border px-0 py-1 text-xs ${
              filters.months.includes(m)
                ? 'border-accent bg-accent/15 text-fg'
                : 'border-border bg-card text-muted'
            }`}
          >
            {m}
          </button>
        ))}
      </div>

      <SectionTitle>Borough</SectionTitle>
      <select
        className={selectClass}
        value={filters.borough}
        onChange={(e) => update({ borough: e.target.value })}
      >
        <option value={BOROUGH_ALL}>{BOROUGH_ALL}</option>
        {(meta?.boroughs ?? []).map((b) => (
          <option key={b} value={b}>
            {b}
          </option>
        ))}
      </select>
    </div>
  )
}
