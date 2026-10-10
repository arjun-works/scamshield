import { useEffect, useRef } from 'react'

// Calls `callback` now and then every `intervalMs`, until the component
// unmounts or `deps` change. The backend serves reads from memory, so
// polling every few seconds is cheap.
export function usePolling(callback, intervalMs, deps = []) {
  const saved = useRef(callback)
  saved.current = callback

  useEffect(() => {
    let cancelled = false
    const tick = () => {
      if (!cancelled) saved.current()
    }
    tick()
    const timer = setInterval(tick, intervalMs)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, ...deps])
}
