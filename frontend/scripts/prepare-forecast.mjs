// Expand the committed forecast table for the frontend to fetch statically.
//
// The forecast long table is large (~840k rows). We commit it gzipped
// (frontend/public/forecast_dashboard_long.json.gz, ~3 MB) to keep the repo lean,
// and expand it to forecast_dashboard_long.json here as a Node prebuild step
// (predev/prebuild) so it works on Vercel's Node build with no Python. Vite then
// copies the expanded JSON from publicDir into the build output, where the SPA
// fetches it at /forecast_dashboard_long.json (see hooks/useCrimeData.ts).
//
// The raw .json is gitignored (regenerated every build); only the .json.gz is
// committed. Uses node:zlib so there is no extra dependency. Generated from the
// model output by backend/scripts/prepare_forecast_artifacts.py.

import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { gunzipSync } from 'node:zlib'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const pub = resolve(here, '../public')
const gzPath = resolve(pub, 'forecast_dashboard_long.json.gz')
const outPath = resolve(pub, 'forecast_dashboard_long.json')

if (!existsSync(gzPath)) {
    // Don't fail the build — the dashboard's historical view does not depend on this;
    // only Forecast mode does. Surface a clear warning so a missing artifact is obvious.
    console.warn(`  forecast: ${gzPath} not found — skipping (Forecast mode will 404)`)
    process.exit(0)
}

const json = gunzipSync(readFileSync(gzPath))
writeFileSync(outPath, json)
console.log(`  forecast: expanded forecast_dashboard_long.json (${(json.length / 1e6).toFixed(1)} MB)`)
