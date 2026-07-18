# UK Crime Explorer

A data-driven decision-support system that maps recorded crime across London and
turns it into a composite **police-demand signal** —
`crime count × severity × preventability` — at LSOA, ward, and borough level.
Built for **TU/e 4CBLW020 — Multidisciplinary Challenge-Based Learning, Group 3**.

The signal is advisory: it ranks where attention is most warranted and shows the
reasoning behind every number; it never prescribes a deployment.

---

## Demo

**Live:** https://uk-crime-explorer.vercel.app/

---

## What it does

- **Composite demand signal.** Combines crime volume, severity, and
  preventability into one comparable score per area, at three resolutions
  (LSOA / ward / borough).
- **Five metric modes.** Raw count · crime share within the selection ·
  severity-weighted · preventability-filtered · composite. A Mean / Median CCHI
  toggle drives the severity and composite modes.
- **Filters + time animation.** Crime type, preventability tier, year, months,
  and borough; an animation that steps through every `(year, month)` period with
  play / pause / reset and a scrubber.
- **Per-LSOA time series.** Click any LSOA to see its last 24 months of monthly
  crime as a sparkline in the recap panel, filtered to the active categories.
- **Forecast (XGBoost).** A forecast mode projecting future demand over 1 / 3 /
  6 / 12-month horizons, trained offline and read from committed artifacts.
- **Allocation.** Three variants over the demand signal — a proportional
  baseline, a linear-programming model that maximises preventable-harm coverage,
  and a Rawlsian variant that lifts the worst-served area — each with a weekly
  deployment schedule. The `/allocation` page summarises the result as a ranking,
  never an instruction.
- **Conversational assistant.** An optional chat with three personas (police
  planner / examiner / community) over one shared data layer. Every quantitative
  claim comes from an explicit tool call and carries an audit badge naming the
  tool that produced it; the assistant ranks and explains, and never prescribes.
- **Methodology page.** `/about` documents the composite signal, severity
  (Cambridge Crime Harm Index 2020), preventability (hot-spot policing
  literature), forecasting, allocation, ethics, and references.

---

## Stack

- **Frontend** — React 18 + TypeScript + Vite. deck.gl choropleth over a
  token-free MapLibre (CARTO) basemap; TanStack Query for server state;
  Tailwind v4 with a runtime light/dark theme. Sparkline is hand-rolled SVG (no
  chart library).
- **Backend** — FastAPI + pandas. The framework-agnostic analysis lives in
  `backend/core/` (data loading, filtering, aggregation, the composite metric,
  and the LP / Rawlsian / proportional allocation models). Forecasting uses
  XGBoost; the live app reads the committed forecast artifacts rather than
  training.
- **Assistant** — Anthropic **Claude Sonnet 4.6**, optional: the chat panel
  hides itself when no API key is configured, leaving the rest of the app
  untouched.
- **Deployment** — Vercel: a static SPA on the CDN plus one lean Python function
  (pandas only — no geopandas — so cold starts stay fast).

---

## Pages

| Route | Page | What it shows |
|---|---|---|
| `/` | Dashboard | The map, sidebar filters, animation, metric modes, side panels, per-LSOA sparkline. |
| `/allocation` | Allocation | LP / Rawlsian / proportional summary with weekly deployment schedules and a per-LSOA breakdown. |
| `/about` | Methodology | The eight-plus-one methodology sections, including the conversational-assistant note. |

---

## API

All routes are under `/api`. Boundary GeoJSON is **not** an API route — it is
served as static assets at `/boundaries/{level}.json`.

| Method | Route | Returns | Called by |
|---|---|---|---|
| GET | `/api/health` | Liveness probe `{status: "ok"}` | smoke tests / uptime |
| GET | `/api/meta` | Years, months, periods, categories (+ metadata), boroughs, tiers | sidebar + map setup |
| POST | `/api/map` | Per-unit values + crime counts + colour-scale bounds for a filter set | the choropleth |
| GET | `/api/weights` | The full category weights table | the sources panel + `/about` |
| GET | `/api/allocation` | LP / Rawlsian / baseline allocation with weekly schedules | the `/allocation` page |
| GET | `/api/timeseries` | One LSOA's last-N-months crime counts (zero-filled), category-filtered | the recap sparkline |
| GET | `/api/chat/health` | Whether the assistant is configured | the nav (shows/hides chat) |
| POST | `/api/chat` | Streaming (SSE) assistant responses with tool calls | the chat panel |

Interactive API docs: `http://127.0.0.1:8000/docs`.

---

## Run locally

Python 3.12 (the geospatial stack pins `numpy==1.26.4`) and Node 20+. The
committed data lets a fresh clone run offline. In separate terminals:

```
cd backend && uvicorn api.main:app --reload     # http://127.0.0.1:8000
cd frontend && npm install && npm run dev        # http://localhost:5173
cd backend && pytest                             # full unit suite
cd backend && pytest -m smoke                    # ~30-second pre-flight
```

The Vite dev server proxies `/api` to the backend, so open
`http://localhost:5173` and the app talks to FastAPI with no extra config. The
backend reads the committed `data/crime_snapshot-london.parquet` (fast, offline);
delete it to force a rebuild.

### Configure the assistant (optional)

The chat panel is optional and hides itself when no key is set. To enable it, set an Anthropic API key in the backend environment:

    ANTHROPIC_API_KEY=sk-ant-...        # required to enable the chat
    ANTHROPIC_MODEL=claude-sonnet-5   # optional; defaults to Sonnet 5

Use a cheaper model (for example claude-haiku-4-5) to cut per-message cost. The codebase is provider-agnostic at the call site, so the chat is the one feature that needs a key; the dashboard, allocation, and methodology pages run fully without one.

---

## Tests

- **Unit suite** (`pytest`) — composite math, metric resolution,
  filtering / aggregation, the API endpoints, and the chat tools, against the
  loaded data.
- **Smoke suite** (`pytest -m smoke`) — opt-in, end-to-end checks against the
  committed real data (`/api/meta`, `/api/map`, `/api/timeseries`, composite
  invariants, chat tools, chat HTTP). No LLM, no network; runs in ~30 seconds.
  See [`backend/tests/smoke/README.md`](backend/tests/smoke/README.md) for the
  morning-of runbook and failure-mode chart.

---

## My role

I owned the dashboard, the data layer beneath it, and the conversational interface built on top.

- Led the migration off Streamlit onto a production stack: FastAPI, React and TypeScript, deck.gl and MapLibre, and a framework-agnostic Python core that the forecasting and allocation tracks import directly.
- Diagnosed and fixed the Vercel deployment failures the cutover initially produced, getting the app live as a static SPA plus one lean Python serverless function.
- Designed and built the conversational assistant: three stakeholder personas, seven grounded tools, expandable audit badges that name the tool behind every number, and an ethical guardrail that keeps it from prescribing an officer count.
- Derived the severity weighting and the preventability multipliers behind the composite signal: the script that turns the Cambridge Crime Harm Index into dual mean and median severity weights, and fourteen preventability multipliers with confidence ratings and one-line literature anchors drawn from Braga, Weisburd, and Sherman, Neyroud and Neyroud.

I brought prior knowledge of full-stack architecture and language-model tool use, and picked up geospatial rendering, the Cambridge crime-harm methodology, and the hot-spot policing literature along the way. The lasting contribution is the live deployment the report references, the methodology the composite signal is built on, the assistant that makes the project legible to a non-technical reader, and the smoke suite, refreshed docs, and runbook that keep it maintainable.

---

## Project context

A TU/e **4CBLW020 — Multidisciplinary Challenge-Based Learning** project,
academic year 2025–2026, Group 3. The brief: build a decision-support tool that
helps a planner reason about where police attention is most warranted, with the
reasoning visible and contestable rather than hidden in a model.

---

## Team

Built by Group 3 for TU/e 4CBLW020 Multidisciplinary Challenge-Based Learning, 2025-2026.

- **Phoebe Dusil** - linear-programming allocation track (LP, Rawlsian, and proportional models), the standalone allocation page and weekly schedules, the anti-overpolicing weights, and the multi-city data layer.
- **Chirila Dragos** - original XGBoost forecasting pipeline and the dashboard forecast view; presented the demo at the final review.
- **Petar Zhelev** - model comparison (XGBoost vs Random Forest vs Negative Binomial) and the native-XGBoost refactor that fixed out-of-memory errors on the Greater London dataset.
- **Daan Weling** - research question and requirements, and the severity-weighting and over-policing research that fed the anti-overpolicing weights.
- **Joep de Bruijn** - the ethics framing the assistant's deployment guardrail is downstream of.
- **Efe Koç** - dashboard rewrite, data layer, conversational assistant, and the severity and preventability methodology (see My role).

This fork is maintained by Efe Koç for personal-portfolio purposes and is not under active team development.

---

## Where things live

- [`backend/tests/smoke/README.md`](backend/tests/smoke/README.md) — smoke-test
  runbook and failure-mode chart.
- [`frontend/README.md`](frontend/README.md) — frontend layout and dev workflow.
- [`backend/scripts/README.md`](backend/scripts/README.md) — the ETL / QA scripts
  and when to re-run each.

---

## Data sources

- **Crime counts** — *London Crime Data, 2008–2016* (Kaggle `jboysen/london-crime`)
  combined with recent monthly extracts from data.police.uk, aggregated to
  LSOA × month × category.
- **Boundaries** — LSOA, ward, and borough boundaries from data.gov.uk.
- **Severity** — *Cambridge Crime Harm Index 2020 Update* (Cambridge Centre for
  Evidence-Based Policing).
- **Preventability** — anchored in Braga et al. (2019), Weisburd (2015, 2021),
  and Sherman, Neyroud & Neyroud (2016).
