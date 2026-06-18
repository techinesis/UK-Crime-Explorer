interface SkeletonProps {
  width?: number | string
  height?: number | string
  className?: string
}

// Content-shaped grey placeholder. A pulsing block sized to whatever it stands
// in for, so the real content lands without a layout shift. CSS-only (Tailwind
// `animate-pulse`) — no spinner, no dependency.
export default function Skeleton({ width, height, className = '' }: SkeletonProps) {
  return (
    <div
      aria-hidden
      className={`animate-pulse rounded bg-surface ${className}`}
      style={{ width, height }}
    />
  )
}
