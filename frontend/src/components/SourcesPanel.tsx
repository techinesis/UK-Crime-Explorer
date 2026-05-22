import type { WeightRow } from '../lib/types'

const CONFIDENCE_EMOJI: Record<string, string> = { High: '🟢', Medium: '🟡', Low: '🔴' }

interface SourcesPanelProps {
  weights?: WeightRow[]
  selected: string[] // empty = show all
}

export default function SourcesPanel({ weights, selected }: SourcesPanelProps) {
  const rows = (weights ?? []).filter(
    (w) => selected.length === 0 || selected.includes(w.category),
  )

  return (
    <section className="rounded-lg border border-border bg-card p-3">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
        Selected category sources
      </h3>
      <ul className="space-y-2">
        {rows.map((w) => (
          <li key={w.category} className="text-xs">
            <div className="font-medium text-fg">
              {CONFIDENCE_EMOJI[w.preventability_confidence] ?? '⚪'} {w.category}
            </div>
            <div className="text-muted">
              {w.preventability_confidence} confidence · {w.preventability_anchor}
            </div>
          </li>
        ))}
        {rows.length === 0 && <li className="text-xs text-muted">No categories.</li>}
      </ul>
    </section>
  )
}
