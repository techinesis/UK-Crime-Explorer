import { useEffect, useState } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { fetchAllocation, fetchMeta, fetchTimeseries, fetchWeights } from './lib/api'
import { useCrimeData } from './hooks/useCrimeData'
import { metricCaption } from './hooks/useFilters'
import { FiltersProvider, useFiltersContext } from './hooks/FiltersContext'
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
import ChatPanel from './components/ChatPanel'
import NavBar from './components/NavBar'
import ErrorBoundary from './components/ErrorBoundary'
import AboutPage from './pages/AboutPage'
import AllocationPage from './pages/AllocationPage'
import { useChatAvailable } from './hooks/useChatHealth'
import type { AllocationRequest } from './lib/types'

export default function App() {
  return (
    <BrowserRouter>
      <ErrorBoundary>
        <FiltersProvider>
          <AppShell />
        </FiltersProvider>
      </ErrorBoundary>
    </BrowserRouter>
  )
}

// Holds the app-wide chrome that must persist across routes: the nav bar and the
// single AI chat panel. The chat lives here (not inside a page) so it is available
// on every route and shares the one FiltersProvider state.
function AppShell() {
  const chatAvailable = useChatAvailable()
  const [chatOpen, setChatOpen] = useState(false)
  const { filters, update } = useFiltersContext()

  return (
    <div className="flex h-screen flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-accent focus:px-3 focus:py-2 focus:text-sm focus:font-medium focus:text-white"
      >
        Skip to main content
      </a>
      <NavBar
        chatAvailable={chatAvailable}
        chatOpen={chatOpen}
        onToggleChat={() => setChatOpen((o) => !o)}
      />
      <div id="main" className="min-h-0 flex-1">
        <Routes>
          <Route
            path="/"
            element={
              <ErrorBoundary>
                <Dashboard />
              </ErrorBoundary>
            }
          />
          <Route
            path="/allocation"
            element={
              <ErrorBoundary>
                <AllocationPage />
              </ErrorBoundary>
            }
          />
          <Route
            path="/about"
            element={
              <ErrorBoundary>
                <AboutPage />
              </ErrorBoundary>
            }
          />
        </Routes>
      </div>

      {chatAvailable && (
        <ChatPanel
          open={chatOpen}
          onClose={() => setChatOpen(false)}
          filters={filters}
          update={update}
        />
      )}
    </div>
  )
}

function Dashboard() {
  const { theme, toggle } = useTheme()
  const { filters, update } = useFiltersContext()

  // The LSOA the user last clicked on the map (null until the first click).
  // Drives the time-series sparkline in the recap panel.
  const [selectedLsoa, setSelectedLsoa] = useState<{
    code: string
    name: string
    borough: string
  } | null>(null)

  const meta = useQuery({ queryKey: ['meta', filters.city], queryFn: () => fetchMeta(filters.city) })
  const weights = useQuery({ queryKey: ['weights', filters.city], queryFn: fetchWeights })
  const allocation = useQuery({
    queryKey: [
      'allocation',
      filters.city,
      filters.totalUnits,
      filters.allocationModel,
      filters.allocationModel !== 'baseline' ? filters.allocMinUnitsPerLsoa : null,
      filters.allocationModel === 'lp' ? filters.allocAlpha : null,
      filters.allocationModel === 'lp' ? filters.allocBeta : null,
      filters.allocationModel === 'lp' ? filters.allocMaxCapFactor : null,
      filters.allocationModel === 'lp' ? filters.allocEquityFloor : null,
    ],
    queryFn: () => {
      const req: AllocationRequest = {
        city: filters.city,
        totalUnits: filters.totalUnits,
        model: filters.allocationModel,
      }
      if (filters.allocationModel !== 'baseline') {
        req.minUnitsPerLsoa = filters.allocMinUnitsPerLsoa
      }
      if (filters.allocationModel === 'lp') {
        req.alpha = filters.allocAlpha
        req.beta = filters.allocBeta
        req.maxCapFactor = filters.allocMaxCapFactor
        req.equityFloor = filters.allocEquityFloor
      }
      return fetchAllocation(req)
    },
  })

  const timeseries = useQuery({
    queryKey: ['timeseries', filters.city, selectedLsoa?.code, filters.categories],
    queryFn: () => fetchTimeseries(selectedLsoa!.code, filters.categories, filters.city),
    enabled: selectedLsoa !== null,
  })

  const { boundaries, map, boroughMap } = useCrimeData(filters)

  const isForecast = filters.mode === 'forecast'

  const baseCaption = metricCaption(filters.metric, filters.severityBasis)
  const caption = isForecast ? `Predicted ${baseCaption.toLowerCase()}` : baseCaption

  const loading = boundaries.isLoading || map.isFetching

  const periods = meta.data?.periods ?? []
  const anim = useAnimation(periods.length)

  // When animating, drive the year/month filters from the current period.
  // This should only happen in historical mode, otherwise it conflicts with forecast mode.
  useEffect(() => {
    if (!anim.enabled || isForecast) return

    const period = periods[anim.index]

    if (period) {
      update({ year: period[0], months: [period[1]] })
    }
  }, [anim.enabled, anim.index, periods, update, isForecast])

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between gap-4 border-b border-border px-5 py-3">
        <div>
          <h1 className="text-lg font-semibold text-fg">London Crime Explorer</h1>
          <p className="text-xs text-muted">
            Police demand signal across London — crime × severity × preventability
          </p>
        </div>

        <div className="flex items-center gap-2">
          <ThemeToggle theme={theme} onToggle={toggle} />
        </div>
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
              isForecast={isForecast}
              metricLabel={caption}
              theme={theme}
              meta={meta.data}
              allocation={allocation.data}
              onSelectLsoa={setSelectedLsoa}
            />
          </div>

          <div className="pointer-events-none absolute left-3 top-3">
            <Legend vmin={map.data?.vmin ?? 0} vmax={map.data?.vmax ?? 1} caption={caption} />
          </div>

          {!isForecast && periods.length > 0 && (
            <div className="pointer-events-none absolute bottom-3 left-1/2 -translate-x-1/2">
              <AnimationControls periods={periods} anim={anim} />
            </div>
          )}

          {isForecast && (
            <div className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-lg bg-card/95 px-4 py-2 text-xs text-muted shadow">
              Forecast mode: showing predicted future police demand
            </div>
          )}

          {loading && (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
              {/* Translucent pulsing wash over the map area — the basemap stays
                  visible underneath so it does not read as a full reload. */}
              <div className="absolute inset-0 animate-pulse bg-surface/40" />
              <span className="relative rounded-md bg-card/90 px-3 py-1.5 text-xs text-muted shadow">
                Loading data…
              </span>
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

          {isForecast && (
            <ForecastSummary
              horizon={filters.forecastHorizon}
              model={filters.forecastModel}
              map={map.data}
            />
          )}

          <SelectionRecap
            filters={filters}
            totalCategories={meta.data?.categories.length ?? 0}
            selectedLsoa={selectedLsoa}
            series={timeseries.data?.series}
            seriesLoading={timeseries.isFetching}
          />

          <TopUnitsPanel
            level={filters.level}
            boundaries={boundaries.data}
            map={map.data}
            metricLabel={caption}
          />

          {isForecast && (
            <ForecastExplanation
              horizon={filters.forecastHorizon}
              selectedCategories={filters.categories}
            />
          )}

          <SourcesPanel weights={weights.data} selected={filters.categories} />
          <BoroughSummary boroughMap={boroughMap.data} />
          <Footer />
        </aside>
      </div>
    </div>
  )
}

type ForecastSummaryProps = {
  horizon: number
  model: string
  map: any
}

function ForecastSummary({ horizon, model, map }: ForecastSummaryProps) {
  const values = getMapValues(map)

  const average =
    values.length > 0 ? values.reduce((sum, value) => sum + value, 0) / values.length : 0

  const max = values.length > 0 ? Math.max(...values) : 0

  return (
    <section className="rounded-lg bg-card p-4 shadow">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-fg">Forecast summary</h2>

        <span className="rounded-full bg-accent/10 px-2 py-1 text-[11px] font-medium text-accent">
          Forecast
        </span>
      </div>

      <p className="mt-2 text-xs text-muted">
        Showing predicted police demand for the next {horizon} month
        {horizon > 1 ? 's' : ''}.
      </p>

      <div className="mt-3 grid grid-cols-2 gap-2 text-sm">
        <div className="rounded-md bg-surface p-2">
          <p className="text-xs text-muted">Average predicted demand</p>
          <p className="font-semibold text-fg">{average.toFixed(1)}</p>
        </div>

        <div className="rounded-md bg-surface p-2">
          <p className="text-xs text-muted">Highest predicted demand</p>
          <p className="font-semibold text-fg">{max.toFixed(1)}</p>
        </div>
      </div>

      <p className="mt-3 text-xs text-muted">
        Model used: <span className="font-medium text-fg">{formatModelName(model)}</span>
      </p>
    </section>
  )
}

type ForecastExplanationProps = {
  horizon: number
  selectedCategories: string[]
}

function ForecastExplanation({ horizon, selectedCategories }: ForecastExplanationProps) {
  return (
    <section className="rounded-lg bg-card p-4 shadow">
      <h2 className="text-sm font-semibold text-fg">Forecast interpretation</h2>

      <p className="mt-2 text-xs text-muted">
        The map highlights areas where police demand is expected to be higher in the next{' '}
        {horizon} month{horizon > 1 ? 's' : ''}.
      </p>

      <p className="mt-2 text-xs text-muted">
        Darker areas represent stronger predicted demand signals. These areas may require earlier
        planning, more monitoring, or possible resource adjustment.
      </p>

      {selectedCategories.length > 0 ? (
        <p className="mt-2 text-xs text-muted">
          The forecast is currently filtered to the selected crime categories.
        </p>
      ) : (
        <p className="mt-2 text-xs text-muted">
          The forecast is currently based on the overall selected demand metric.
        </p>
      )}
    </section>
  )
}

function getMapValues(map: any): number[] {
  if (!map) return []

  if (Array.isArray(map.values)) {
    return map.values.filter((value: unknown) => typeof value === 'number' && Number.isFinite(value))
  }

  if (map.values && typeof map.values === 'object') {
    return Object.values(map.values).filter(
      (value): value is number => typeof value === 'number' && Number.isFinite(value),
    )
  }

  if (Array.isArray(map.rows)) {
    return map.rows
      .map((row: any) => row.value ?? row.metric ?? row.demand ?? row.prediction)
      .filter((value: unknown) => typeof value === 'number' && Number.isFinite(value))
  }

  if (Array.isArray(map.data)) {
    return map.data
      .map((row: any) => row.value ?? row.metric ?? row.demand ?? row.prediction)
      .filter((value: unknown) => typeof value === 'number' && Number.isFinite(value))
  }

  return []
}

function formatModelName(model: string) {
  if (model === 'xgboost') return 'XGBoost'
  if (model === 'baseline') return 'Seasonal baseline'
  return model
}
