import { useEffect, useState } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
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
import ChatPanel from './components/ChatPanel'
import NavBar from './components/NavBar'
import AboutPage from './pages/AboutPage'
import { useChatAvailable } from './hooks/useChatHealth'

export default function App() {
  return (
    <BrowserRouter>
      <div className="flex h-screen flex-col">
        <NavBar />
        <div className="min-h-0 flex-1">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/about" element={<AboutPage />} />
          </Routes>
        </div>
      </div>
    </BrowserRouter>
  )
}

function Dashboard() {
  const { theme, toggle } = useTheme()
  const { filters, update } = useFilters()

  // AI chat panel: only shown when the backend reports it is configured
  // (ANTHROPIC_API_KEY + deps present). Collapsed by default.
  const chatAvailable = useChatAvailable()
  const [chatOpen, setChatOpen] = useState(false)

  const meta = useQuery({ queryKey: ['meta'], queryFn: fetchMeta })
  const weights = useQuery({ queryKey: ['weights'], queryFn: fetchWeights })

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
          {chatAvailable && (
            <button
              onClick={() => setChatOpen((o) => !o)}
              aria-pressed={chatOpen}
              className="rounded-md border border-border bg-card px-3 py-1.5 text-xs font-medium text-fg hover:border-accent"
            >
              💬 Assistant
            </button>
          )}
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
              metricLabel={caption}
              theme={theme}
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

          {isForecast && (
            <ForecastSummary
              horizon={filters.forecastHorizon}
              model={filters.forecastModel}
              map={map.data}
            />
          )}

          <SelectionRecap filters={filters} totalCategories={meta.data?.categories.length ?? 0} />

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
