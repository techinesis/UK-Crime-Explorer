import type { TimeseriesPoint } from '../lib/types'

interface TimeSeriesSparklineProps {
  series: TimeseriesPoint[]
  lsoaName?: string
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function monthLabel(p: { year: number; month: number }): string {
  return `${MONTHS[p.month - 1] ?? p.month} '${String(p.year).slice(2)}`
}

// SVG geometry (the viewBox the chart is drawn in). Kept fixed at 240×60 to
// match the loading Skeleton, so the chart lands with no layout shift.
const W = 240
const H = 60
const PAD_X = 4
const TOP = 13 // leaves room for the max-value label
const BOTTOM = 46 // leaves room for the month labels

// Hand-rolled sparkline — one polyline, a few axis labels, no chart library.
export default function TimeSeriesSparkline({ series, lsoaName }: TimeSeriesSparklineProps) {
  if (series.length === 0) {
    return <p className="text-xs text-muted">No data for this filter</p>
  }

  const counts = series.map((p) => p.count)
  const max = Math.max(...counts, 0)
  const peak = series[counts.indexOf(max)] ?? series[series.length - 1]
  const n = series.length
  const span = W - PAD_X * 2

  const points = series
    .map((p, i) => {
      const x = n === 1 ? W / 2 : PAD_X + (i / (n - 1)) * span
      // Flat line at the bottom when every month is zero.
      const y = max === 0 ? BOTTOM : BOTTOM - (p.count / max) * (BOTTOM - TOP)
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')

  const summary =
    max === 0
      ? `Monthly crime${lsoaName ? ` in ${lsoaName}` : ''}: no recorded crime over the last ${n} months.`
      : `Monthly crime${lsoaName ? ` in ${lsoaName}` : ''}: peak ${max} in ${monthLabel(peak)}, over the last ${n} months.`

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" aria-label={summary}>
      <polyline
        points={points}
        fill="none"
        className="stroke-accent"
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
      <text x={PAD_X} y={9} fontSize={9} className="fill-muted">
        {max.toLocaleString()}
      </text>
      <text x={PAD_X} y={H - 2} fontSize={8} className="fill-muted">
        {monthLabel(series[0])}
      </text>
      <text x={W - PAD_X} y={H - 2} fontSize={8} textAnchor="end" className="fill-muted">
        {monthLabel(series[n - 1])}
      </text>
    </svg>
  )
}
