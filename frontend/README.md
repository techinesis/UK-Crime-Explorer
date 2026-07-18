# UK Crime Explorer — frontend

The single-page app: a deck.gl + MapLibre choropleth of London crime with a
sidebar of filters, a forecast view, an allocation page, an `/about` methodology
page, and an optional AI assistant. **Vite + React 18 + TypeScript**, styled with
Tailwind v4 (runtime light/dark theme), server state via TanStack Query.

## Run it

```
npm install
npm run dev          # http://localhost:5173
```

The dev server proxies `/api/*` to the FastAPI backend on `:8000`, so start the
backend too (`cd backend && uvicorn api.main:app --reload`). Boundary GeoJSON is
served from `public/boundaries/*.json` (see below).

## Build

```
npm run build        # type-checks (tsc -b) then bundles with Vite
```

Vite's `build.outDir` is `../public`, so the build emits the SPA (and the
pre-baked boundaries) into the **repo-root `public/`** that Vercel serves as the
static site. `npm run preview` serves that build locally.

## Pre-baked boundary GeoJSONs

Boundaries are **not** an API route — they are static assets. `scripts/prepare-static.mjs`
(and `scripts/prepare-forecast.mjs`) run automatically on `predev` / `prebuild`,
copying the cleaned GeoJSON from `data/*_boundaries_clean.geojson` into
`public/boundaries/{lsoa,ward,borough}.json` and emitting `data/unit_ids.json`
(the per-level id list the backend uses to 0-fill empty units). deck.gl renders
the full geometry on the GPU, so it is shipped unsimplified.

## Layout

```
src/
  App.tsx          router shell + the Dashboard route (map, sidebar, side panels)
  pages/           AllocationPage (LP/Rawls/averaging summary), AboutPage (methodology)
  components/      CrimeMap, Sidebar, Legend, AnimationControls, SummaryStats,
                   TopUnitsPanel, SelectionRecap, BoroughSummary, SourcesPanel,
                   ThemeToggle, NavBar, Footer, ChatPanel, ChatMarkdown,
                   FilterContextPills, TimeSeriesSparkline, ErrorBoundary, Skeleton
  hooks/           useFilters + FiltersContext, useCrimeData, useAnimation,
                   useChatHealth, useTheme
  lib/             api (typed fetch), types (mirror backend schemas), colors (YlOrRd ramp)
```

The Dashboard route lives inside `App.tsx`; `pages/` holds the two secondary
routes. State is held in one `FiltersProvider` (so the chat shares it across
routes); the map/meta/weights/allocation/timeseries fetches are TanStack queries.

## Where to read more

The root [`README.md`](../README.md) covers the full stack, the API routes, the
deployment model, and how to run the backend and tests.
