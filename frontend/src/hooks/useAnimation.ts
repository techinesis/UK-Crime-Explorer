import { useCallback, useEffect, useState } from 'react'

const FRAME_INTERVAL_MS = 700 // matches the Streamlit animation cadence

export interface Animation {
  enabled: boolean
  playing: boolean
  index: number
  setEnabled: (on: boolean) => void
  play: () => void
  pause: () => void
  reset: () => void
  scrub: (index: number) => void
}

/**
 * Steps an index through `periodCount` frames on a timer. React owns the loop
 * via setInterval in an effect (no server reruns, unlike the Streamlit version).
 */
export function useAnimation(periodCount: number): Animation {
  const [enabled, setEnabledState] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [index, setIndex] = useState(0)

  useEffect(() => {
    if (!enabled || !playing || periodCount === 0) return
    const timer = setInterval(() => {
      setIndex((i) => {
        if (i + 1 >= periodCount) {
          setPlaying(false)
          return i
        }
        return i + 1
      })
    }, FRAME_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [enabled, playing, periodCount])

  const setEnabled = useCallback((on: boolean) => {
    setEnabledState(on)
    if (!on) setPlaying(false)
  }, [])

  const play = useCallback(() => setPlaying(true), [])
  const pause = useCallback(() => setPlaying(false), [])
  const reset = useCallback(() => {
    setPlaying(false)
    setIndex(0)
  }, [])
  const scrub = useCallback((i: number) => {
    setPlaying(false)
    setIndex(i)
  }, [])

  return { enabled, playing, index, setEnabled, play, pause, reset, scrub }
}
