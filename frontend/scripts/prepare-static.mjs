// Pre-bake boundary GeoJSON as static assets + the unit-id index the API needs.
//
// Runs as a Node prebuild step (predev/prebuild) so it works on Vercel's Node
// build with no Python/geopandas. Reads the committed boundary GeoJSON from
// ../data, trims feature properties to id + tooltip fields, writes:
//   - frontend/public/boundaries/{level}.json   (served statically by the CDN)
//   - data/unit_ids.json                          (read by the Python function
//                                                   to 0-fill empty units)

import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const dataDir = resolve(here, '../../data')
const outDir = resolve(here, '../public/boundaries')
mkdirSync(outDir, { recursive: true })

const LEVELS = {
    lsoa: { file: 'lsoa_boundaries_clean.geojson', id: 'lsoa_code', keep: ['lsoa_code', 'lsoa_name', 'borough'] },
    ward: { file: 'london_ward_boundaries_clean.geojson', id: 'ward_code', keep: ['ward_code', 'ward_name', 'borough'] },
    borough: { file: 'london_borough_boundaries_clean.geojson', id: 'borough', keep: ['borough'] },
}

const unitIds = {}

for (const [level, cfg] of Object.entries(LEVELS)) {
    const fc = JSON.parse(readFileSync(resolve(dataDir, cfg.file), 'utf8'))
    const ids = new Set()
    for (const feature of fc.features) {
        const trimmed = {}
        for (const key of cfg.keep) {
            if (key in feature.properties) trimmed[key] = feature.properties[key]
        }
        feature.properties = trimmed
        ids.add(String(trimmed[cfg.id]))
    }
    writeFileSync(resolve(outDir, `${level}.json`), JSON.stringify(fc))
    unitIds[level] = [...ids]
    console.log(`  ${level}: ${fc.features.length} features, ${ids.size} units`)
}

writeFileSync(resolve(dataDir, 'unit_ids.json'), JSON.stringify(unitIds))
console.log('prepared static boundaries + data/unit_ids.json')
