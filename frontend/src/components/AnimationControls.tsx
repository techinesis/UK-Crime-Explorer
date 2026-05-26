import type { Animation } from '../hooks/useAnimation'

interface AnimationControlsProps {
  periods: Array<[number, number]>
  anim: Animation
}

function label(period: [number, number] | undefined): string {
  if (!period) return '—'
  const [year, month] = period
  return `${year}-${String(month).padStart(2, '0')}`
}

const btn =
  'rounded-md border border-border bg-card px-2 py-1 text-sm text-fg hover:border-accent disabled:opacity-40'

export default function AnimationControls({ periods, anim }: AnimationControlsProps) {
  const max = Math.max(periods.length - 1, 0)

  return (
    <div className="pointer-events-auto flex items-center gap-3 rounded-lg border border-border bg-card/90 px-3 py-2 text-fg shadow-lg backdrop-blur">
      <label className="flex items-center gap-1.5 text-xs">
        <input
          type="checkbox"
          checked={anim.enabled}
          onChange={(e) => anim.setEnabled(e.target.checked)}
          className="accent-accent"
        />
        Animate
      </label>

      <button type="button" className={btn} disabled={!anim.enabled} onClick={anim.reset} title="Reset">
        ⏮
      </button>
      {anim.playing ? (
        <button type="button" className={btn} disabled={!anim.enabled} onClick={anim.pause}>
          ⏸ Pause
        </button>
      ) : (
        <button type="button" className={btn} disabled={!anim.enabled} onClick={anim.play}>
          ▶ Play
        </button>
      )}

      <input
        type="range"
        min={0}
        max={max}
        value={Math.min(anim.index, max)}
        disabled={!anim.enabled}
        onChange={(e) => anim.scrub(Number(e.target.value))}
        className="w-48 accent-accent disabled:opacity-40"
      />
      <span className="w-16 text-center text-sm tabular-nums">{label(periods[anim.index])}</span>
    </div>
  )
}
