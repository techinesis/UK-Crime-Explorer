import { rampCss } from '../lib/colors'

interface LegendProps {
  vmin: number
  vmax: number
  caption: string
}

const fmt = (n: number) => n.toLocaleString(undefined, { maximumFractionDigits: 1 })

export default function Legend({ vmin, vmax, caption }: LegendProps) {
  const stops = Array.from({ length: 11 }, (_, i) => rampCss(i / 10)).join(', ')
  return (
    <div className="rounded-lg border border-border bg-card/90 px-3 py-2 text-xs text-fg shadow-lg backdrop-blur">
      <div className="mb-1 max-w-56 font-medium leading-tight">{caption}</div>
      <div
        className="h-3 w-52 rounded"
        style={{ background: `linear-gradient(to right, ${stops})` }}
      />
      <div className="mt-1 flex w-52 justify-between text-muted">
        <span>{fmt(vmin)}</span>
        <span>{fmt(vmax)}</span>
      </div>
    </div>
  )
}
