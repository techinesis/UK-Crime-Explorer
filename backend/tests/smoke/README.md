# Smoke tests

Fast, opt-in, end-to-end checks that exercise the whole stack against the
**committed real data** — `/api/meta`, `/api/map`, `/api/timeseries`, the
composite math, the chat tools, and the chat HTTP layer (health, SSE, rate
limit). **No LLM call, no network.** Run them the morning of a demo to catch a
silent regression before it shows up on screen.

## Morning-of runbook

1. From the repo root: `cd backend && pytest -m smoke -v`.
2. Expect **under 30 seconds** and a green bar.
3. If anything fails, find the test in the failure-mode chart below to see which
   layer is most likely at fault and where to look first.

The suite is opt-in: plain `pytest` runs only the unit tests. Only `-m smoke`
runs these.

## Failure-mode chart

| Test | Likely layer | First place to look |
|---|---|---|
| `test_meta_endpoint` | data load | is `data/crime_snapshot-london.parquet` present? |
| `test_map_endpoints` | a map mode regressed | `core/composite.py`, `core/geometry.py` |
| `test_timeseries` | timeseries endpoint | the `/api/timeseries` route in `api/main.py` |
| `test_composite_invariants` | composite math drift | `core/data.py` or `core/weights.py` |
| `test_chat_tools` | tool registry mismatch | `core/chat.py` |
| `test_chat_http` | chat HTTP layer | `api/chat.py`, `api/main.py` |
| `test_set_filters_city_roundtrip` | city normalization | `core/chat.py` normalize_filters |
| `test_api_health` | app boot / import | `api/main.py` |
| `test_forecast` / `test_allocation` | forecast/allocation | ask the branch owner |
