// Client-side YlOrRd colour ramp, reproducing app.py's matplotlib colouring:
// Normalize(vmin, vmax) -> YlOrRd, alpha 200 for present units (including zero),
// grey for units missing from the values map.

import { interpolateYlOrRd } from 'd3-scale-chromatic'

export type RGBA = [number, number, number, number]

const GREY: RGBA = [200, 200, 200, 100]
const ALPHA = 200
const RAMP_STEPS = 256

// Pre-rasterise the ramp once so per-feature colouring is a cheap array lookup.
const RAMP: Array<[number, number, number]> = Array.from({ length: RAMP_STEPS }, (_, i) =>
  parseRgb(interpolateYlOrRd(i / (RAMP_STEPS - 1))),
)

function parseRgb(value: string): [number, number, number] {
  const match = value.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/)
  if (!match) return [200, 200, 200]
  return [Number(match[1]), Number(match[2]), Number(match[3])]
}

function clamp01(t: number): number {
  if (t < 0) return 0
  if (t > 1) return 1
  return t
}

/** Colour for a single unit value given the active scale bounds. */
export function rgbaForValue(
  value: number | undefined,
  vmin: number,
  vmax: number,
): RGBA {
  if (value === undefined || value === null || Number.isNaN(value)) return GREY
  const span = vmax - vmin
  const t = span > 0 ? clamp01((value - vmin) / span) : 0
  const [r, g, b] = RAMP[Math.round(t * (RAMP_STEPS - 1))]
  return [r, g, b, ALPHA]
}

/** CSS rgb() string at scale position t in [0, 1] — for the legend gradient. */
export function rampCss(t: number): string {
  const [r, g, b] = RAMP[Math.round(clamp01(t) * (RAMP_STEPS - 1))]
  return `rgb(${r}, ${g}, ${b})`
}
