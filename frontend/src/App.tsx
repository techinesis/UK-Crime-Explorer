import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchMeta, fetchWeights } from './lib/api'
import { useCrimeData } from './hooks/useCrimeData'
import { metricCaption, useFilters } from './hooks/useFilters'
import { useAnimation } from './hooks/useAnimation'
import { useTheme } from './hooks/useTheme'
import CrimeMap from './components/CrimeMap'
import Sidebar from './components/Sidebar'
import Legend from './components/Legend'
import AnimationControls from './components/AnimationControls'
import ThemeToggle from './components/ThemeToggle'
import SummaryStats from './components/SummaryStats'
import TopUnitsPanel from './components/TopUnitsPanel'
import SourcesPanel from './components/SourcesPanel'
import SelectionRecap from './components/SelectionRecap'
import BoroughSummary from './components/BoroughSummary'
import Footer from './components/Footer'

export default function App() {
  const { theme, toggle } = useTheme()
  const { filters, update } = useFilters()
  const meta = useQuery({ queryKey: ['meta'], queryFn: fetchMeta })
  const weights = useQuery({ queryKey: ['weights'], queryFn: fetchWeights })
  const { boundaries, map, boroughMap } = useCrimeData(filters)
  const caption = metricCaption(filters.metric, filters.severityBasis)
  const loading = boundaries.isLoading || map.isFetching

  const periods = meta.data?.periods ?? []
  const anim = useAnimation(periods.length)

  // When animating, drive the year/month filters from the current period.
  useEffect(() => {
    if (!anim.enabled) return
    const period = periods[anim.index]
    if (period) update({ year: period[0], months: [period[1]] })
  }, [anim.enabled, anim.index, periods, update])

  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center justify-between gap-4 border-b border-border px-5 py-3">
        <div>
          <h1 className="text-lg font-semibold text-fg">London Crime Explorer</h1>
          <p className="text-xs text-muted">
            Police demand signal across London — crime × severity × preventability
          </p>
        </div>
        <ThemeToggle theme={theme} onToggle={toggle} />
      </header>

      <div className="flex min-h-0 flex-1">
        <aside className="w-80 shrink-0 overflow-y-auto border-r border-border bg-sidebar p-4">
          <Sidebar meta={meta.data} filters={filters} update={update} />
        </aside>

        <main className="relative min-w-0 flex-1">
          <div className="absolute inset-0">
            <CrimeMap
              boundaries={boundaries.data}
              map={map.data}
              level={filters.level}
              borough={filters.borough}
              metricLabel={caption}
              theme={theme}
            />
          </div>

          <div className="pointer-events-none absolute left-3 top-3">
            <Legend vmin={map.data?.vmin ?? 0} vmax={map.data?.vmax ?? 1} caption={caption} />
          </div>

          {periods.length > 0 && (
            <div className="pointer-events-none absolute bottom-3 left-1/2 -translate-x-1/2">
              <AnimationControls periods={periods} anim={anim} />
            </div>
          )}

          {loading && (
            <div className="absolute right-3 top-3 rounded-md bg-card/90 px-3 py-1 text-xs text-muted shadow">
              Loading…
            </div>
          )}
          {map.error && (
            <div className="absolute bottom-3 left-3 rounded-md bg-red-900/80 px-3 py-1 text-xs text-red-100 shadow">
              {(map.error as Error).message}
            </div>
          )}
        </main>

        <aside className="flex w-96 shrink-0 flex-col gap-3 overflow-y-auto border-l border-border bg-surface p-4">
          <SummaryStats level={filters.level} map={map.data} />
          <SelectionRecap filters={filters} totalCategories={meta.data?.categories.length ?? 0} />
          <TopUnitsPanel
            level={filters.level}
            boundaries={boundaries.data}
            map={map.data}
            metricLabel={caption}
          />
          <SourcesPanel weights={weights.data} selected={filters.categories} />
          <BoroughSummary boroughMap={boroughMap.data} />
          <Footer />
        </aside>
      </div>
    </div>
  )
}
