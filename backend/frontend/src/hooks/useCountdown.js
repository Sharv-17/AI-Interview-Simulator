import { useEffect, useState } from 'react'

// Seconds left until `endsAtMs` (a Date.now() timestamp). Returns null when there is no deadline.
export function useCountdown(endsAtMs) {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!endsAtMs) return undefined
    const timer = setInterval(() => setNow(Date.now()), 250)
    return () => clearInterval(timer)
  }, [endsAtMs])

  if (!endsAtMs) return null
  return Math.max(0, (endsAtMs - now) / 1000)
}
