import { useMemo } from 'react'
import type { MapResponse } from '../lib/types'

interface BoroughSummaryProps {
  boroughMap?: MapResponse
}

export default function BoroughSummary({ boroughMap }: BoroughSummaryProps) {
  const rows = useMemo(() => {
    if (!boroughMap) return []
    return Object.entries(boroughMap.crime_counts)
      .map(([borough, count]) => ({ borough, count }))
      .sort((a, b) => b.count - a.count)
  }, [boroughMap])

  return (
    <section className="rounded-lg border border-border bg-card p-3">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
        Borough summary (crime count)
      </h3>
      <div className="max-h-56 overflow-y-auto">
        <table className="w-full text-xs text-fg">
          <tbody>
            {rows.map((r) => (
              <tr key={r.borough} className="border-b border-border/60 last:border-0">
                <td className="py-0.5 pr-2">{r.borough}</td>
                <td className="py-0.5 text-right tabular-nums text-muted">
                  {Math.round(r.count).toLocaleString()}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td className="py-2 text-muted">No data.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}
