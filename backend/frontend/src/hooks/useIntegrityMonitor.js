import { useCallback, useEffect, useRef } from 'react'

// Collects the client-side indicators the backend accepts: copy, paste, tab_switch, focus_loss.
// It never reads clipboard contents. Events are buffered and sent with the answer
// (or flushed separately if the question ends without one).
export function useIntegrityMonitor(enabled) {
  const buffer = useRef([])
  const hiddenAt = useRef(null)
  const blurredAt = useRef(null)
  const hiddenDuringBlur = useRef(false)

  const push = useCallback((event) => {
    buffer.current.push({ occurred_at: new Date().toISOString(), ...event })
  }, [])

  useEffect(() => {
    if (!enabled) return undefined

    function onVisibilityChange() {
      if (document.visibilityState === 'hidden') {
        hiddenAt.current = Date.now()
        hiddenDuringBlur.current = true
      } else if (hiddenAt.current !== null) {
        push({ event_type: 'tab_switch', duration_ms: Date.now() - hiddenAt.current })
        hiddenAt.current = null
      }
    }

    function onBlur() {
      blurredAt.current = Date.now()
      hiddenDuringBlur.current = false
    }

    function onFocus() {
      // Switching tabs fires both blur and visibilitychange; count it once, as a tab switch.
      if (blurredAt.current !== null && !hiddenDuringBlur.current) {
        push({ event_type: 'focus_loss', duration_ms: Date.now() - blurredAt.current })
      }
      blurredAt.current = null
    }

    document.addEventListener('visibilitychange', onVisibilityChange)
    window.addEventListener('blur', onBlur)
    window.addEventListener('focus', onFocus)
    return () => {
      document.removeEventListener('visibilitychange', onVisibilityChange)
      window.removeEventListener('blur', onBlur)
      window.removeEventListener('focus', onFocus)
    }
  }, [enabled, push])

  const recordCopy = useCallback(() => push({ event_type: 'copy', source: 'answer_box' }), [push])
  const recordPaste = useCallback(() => push({ event_type: 'paste', source: 'answer_box' }), [push])

  // Removes and returns everything collected so far.
  const drain = useCallback(() => {
    const events = buffer.current
    buffer.current = []
    return events
  }, [])

  const reset = useCallback(() => {
    buffer.current = []
    hiddenAt.current = null
    blurredAt.current = null
  }, [])

  return { recordCopy, recordPaste, drain, reset }
}
