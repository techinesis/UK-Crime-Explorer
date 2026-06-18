import type { FilterState } from '../hooks/useFilters'
import { METRIC_OPTIONS } from '../hooks/useFilters'
import type { TimeseriesPoint } from '../lib/types'
import Skeleton from './Skeleton'
import TimeSeriesSparkline from './TimeSeriesSparkline'

interface SelectionRecapProps {
  filters: FilterState
  totalCategories: number
  selectedLsoa?: { code: string; name: string; borough: string } | null
  series?: TimeseriesPoint[]
  seriesLoading?: boolean
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2 py-0.5">
      <span className="text-muted">{label}</span>
      <span className="text-right text-fg">{value}</span>
    </div>
  )
}

export default function SelectionRecap({
  filters,
  totalCategories,
  selectedLsoa,
  series,
  seriesLoading,
}: SelectionRecapProps) {
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

      <div className="mt-3 border-t border-border pt-2">
        <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">
          LSOA trend
        </h4>
        {selectedLsoa ? (
          <>
            <p className="mb-1 font-medium text-fg">{selectedLsoa.name}</p>
            {seriesLoading ? (
              <Skeleton width={240} height={60} />
            ) : (
              <TimeSeriesSparkline series={series ?? []} lsoaName={selectedLsoa.name} />
            )}
          </>
        ) : (
          <p className="text-muted">Click an LSOA on the map to see its 24-month trend.</p>
        )}
      </div>
    </section>
  )
}
