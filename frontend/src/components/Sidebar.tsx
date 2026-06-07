import type { ReactNode } from 'react'
import type { MetaResponse } from '../lib/types'
import {
  BOROUGH_ALL,
  FORECAST_HORIZON_OPTIONS,
  FORECAST_MODE_OPTIONS,
  FORECAST_MODEL_OPTIONS,
  LEVEL_OPTIONS,
  METRIC_OPTIONS,
  TIER_ALL,
  YEAR_ALL,
  CITIES,
  type FilterState,
} from '../hooks/useFilters'

const CONFIDENCE_EMOJI: Record<string, string> = {
  High: '🟢',
  Medium: '🟡',
  Low: '🔴',
}

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

function SectionTitle({ children }: { children: ReactNode }) {
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

    if (set.has(name)) {
      set.delete(name)
    } else {
      set.add(name)
    }

    update({ categories: [...set] })
  }

  const toggleMonth = (month: number) => {
    const set = new Set(filters.months)

    if (set.has(month)) {
      set.delete(month)
    } else {
      set.add(month)
    }

    update({ months: [...set].sort((a, b) => a - b) })
  }

  const isForecast = filters.mode === 'forecast'

  return (
    <div className="space-y-1 text-fg">
      <SectionTitle>Forecasting</SectionTitle>

      <div className="rounded-lg border border-border bg-card p-3">
        <p className="mb-2 text-[11px] text-muted">
          Switch between historical crime demand and predicted future demand.
        </p>

        <div className="flex gap-2">
          {FORECAST_MODE_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => update({ mode: option.value })}
              className={toggleClass(filters.mode === option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>

        {isForecast && (
          <div className="mt-3 space-y-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-muted">
                Forecast horizon
              </label>

              <select
                className={selectClass}
                value={filters.forecastHorizon}
                onChange={(e) => update({ forecastHorizon: Number(e.target.value) })}
              >
                {FORECAST_HORIZON_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="mb-1 block text-xs font-medium text-muted">
                Forecast model
              </label>

              <select
                className={selectClass}
                value={filters.forecastModel}
                onChange={(e) =>
                  update({ forecastModel: e.target.value as FilterState['forecastModel'] })
                }
              >
                {FORECAST_MODEL_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>

            <p className="rounded-md bg-surface p-2 text-[11px] text-muted">
              In forecast mode, the map should use predicted future values instead of historical
              monthly counts.
            </p>
          </div>
        )}
      </div>

      <SectionTitle>Map mode</SectionTitle>

      <select
        className={selectClass}
        value={filters.metric}
        onChange={(e) => update({ metric: e.target.value as FilterState['metric'] })}
      >
        {METRIC_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>

      <SectionTitle>Severity basis</SectionTitle>

      <div className="flex gap-2">
        {(['mean', 'median'] as const).map((basis) => (
          <button
            key={basis}
            type="button"
            onClick={() => update({ severityBasis: basis })}
            className={toggleClass(filters.severityBasis === basis)}
          >
            {basis === 'mean' ? 'Mean CCHI' : 'Median CCHI'}
          </button>
        ))}
      </div>

      <SectionTitle>Aggregation level</SectionTitle>

      <div className="flex gap-2">
        {LEVEL_OPTIONS.map((option) => (
          <button
            key={option.value}
            type="button"
            onClick={() => update({ level: option.value })}
            className={toggleClass(filters.level === option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>

      <SectionTitle>Crime type</SectionTitle>

      <p className="mb-1 text-[11px] text-muted">
        🟢/🟡/🔴 = preventability evidence strength. Empty = all.
      </p>

      <div className="max-h-44 space-y-0.5 overflow-y-auto rounded-md border border-border bg-card p-2">
        {(meta?.categories ?? []).map((category) => {
          const emoji =
            CONFIDENCE_EMOJI[confidenceByCategory.get(category.name) ?? 'Low'] ?? '⚪'

          const checked = filters.categories.includes(category.name)

          return (
            <label key={category.name} className="flex cursor-pointer items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={checked}
                onChange={() => toggleCategory(category.name)}
                className="accent-accent"
              />

              <span>
                {emoji} {category.name}
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
        {[TIER_ALL, 'High', 'Medium', 'Low'].map((tier) => (
          <option key={tier} value={tier}>
            {tier}
          </option>
        ))}
      </select>

      {!isForecast && (
        <>
          <SectionTitle>Year</SectionTitle>

          <select
            className={selectClass}
            value={filters.year === null ? YEAR_ALL : String(filters.year)}
            onChange={(e) =>
              update({
                year: e.target.value === YEAR_ALL ? null : Number(e.target.value),
              })
            }
          >
            <option value={YEAR_ALL}>{YEAR_ALL}</option>

            {(meta?.years ?? []).map((year) => (
              <option key={year} value={year}>
                {year}
              </option>
            ))}
          </select>

          <SectionTitle>Months</SectionTitle>

          <div className="grid grid-cols-6 gap-1">
            {(meta?.months ?? []).map((month) => (
              <button
                key={month}
                type="button"
                onClick={() => toggleMonth(month)}
                className={`rounded border px-0 py-1 text-xs ${
                  filters.months.includes(month)
                    ? 'border-accent bg-accent/15 text-fg'
                    : 'border-border bg-card text-muted'
                }`}
              >
                {month}
              </button>
            ))}
          </div>

          <SectionTitle>City</SectionTitle>

          <select
            className={selectClass}
            value={String(filters.city)}
            onChange={(e) =>
              update({
                city: e.target.value,
              })
            }
          >
            {(CITIES.map((city) => (
              <option key={city} value={city}>
                {city}
              </option>
            )))}
          </select>
        </>
      )}

      {isForecast && (
        <div className="mt-4 rounded-md border border-border bg-card p-3">
          <p className="text-xs font-medium text-fg">Time filters hidden</p>
          <p className="mt-1 text-[11px] text-muted">
            Year and month are not shown because the forecast horizon controls the future period.
          </p>
        </div>
      )}

      <SectionTitle>Borough</SectionTitle>

      <select
        className={selectClass}
        value={filters.borough}
        onChange={(e) => update({ borough: e.target.value })}
      >
        <option value={BOROUGH_ALL}>{BOROUGH_ALL}</option>

        {(meta?.boroughs ?? []).map((borough) => (
          <option key={borough} value={borough}>
            {borough}
          </option>
        ))}
      </select>
    </div>
  )
}
