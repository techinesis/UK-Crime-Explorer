import type { FilterState } from '../hooks/useFilters'
import { METRIC_OPTIONS } from '../hooks/useFilters'

interface SelectionRecapProps {
  filters: FilterState
  totalCategories: number
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2 py-0.5">
      <span className="text-muted">{label}</span>
      <span className="text-right text-fg">{value}</span>
    </div>
  )
}

export default function SelectionRecap({ filters, totalCategories }: SelectionRecapProps) {
  const metricLabel = METRIC_OPTIONS.find((o) => o.value === filters.metric)?.label ?? filters.metric
  const cats =
    filters.categories.length === 0
      ? `All (${totalCategories})`
      : `${filters.categories.length} selected`
  const months = filters.months.length === 0 ? 'All' : filters.months.join(', ')

  return (
    <section className="rounded-lg border border-border bg-card p-3 text-xs">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
        Current selection
      </h3>
      <Row label="Map mode" value={metricLabel} />
      <Row label="Severity basis" value={filters.severityBasis === 'mean' ? 'Mean CCHI' : 'Median CCHI'} />
      <Row label="Level" value={filters.level.toUpperCase()} />
      <Row label="Crime types" value={cats} />
      <Row label="Tier" value={filters.tier} />
      <Row label="Year" value={filters.year === null ? 'All years' : String(filters.year)} />
      <Row label="Months" value={months} />
      <Row label="Borough" value={filters.borough} />
      <Row label="City" value={filters.city} />
    </section>
  )
}
