import { useCallback, useEffect, useRef, useState } from 'react'

// Formats the backend accepts: WebM, Ogg, MP4/M4A, WAV, MP3.
const CANDIDATE_TYPES = [
  { mime: 'audio/webm;codecs=opus', ext: 'webm' },
  { mime: 'audio/webm', ext: 'webm' },
  { mime: 'audio/ogg;codecs=opus', ext: 'ogg' },
  { mime: 'audio/mp4', ext: 'm4a' },
]

function pickType() {
  if (typeof window === 'undefined' || typeof window.MediaRecorder === 'undefined') return null
  return CANDIDATE_TYPES.find((t) => window.MediaRecorder.isTypeSupported(t.mime)) || null
}

export const voiceSupported = () =>
  typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia && pickType() !== null

// Records one clip at a time. `onFinished(blob, filename)` is called when recording stops.
export function useVoiceRecorder({ maxSeconds, onFinished }) {
  const [recording, setRecording] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState('')
  const recorderRef = useRef(null)
  const streamRef = useRef(null)
  const timerRef = useRef(null)
  const stopTimeoutRef = useRef(null)
  const onFinishedRef = useRef(onFinished)

  useEffect(() => {
    onFinishedRef.current = onFinished
  }, [onFinished])

  const cleanup = useCallback(() => {
    clearInterval(timerRef.current)
    clearTimeout(stopTimeoutRef.current)
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
  }, [])

  const stop = useCallback(() => {
    const recorder = recorderRef.current
    if (recorder && recorder.state !== 'inactive') recorder.stop()
  }, [])

  const start = useCallback(async () => {
    setError('')
    const type = pickType()
    if (!type) {
      setError('This browser cannot record audio. Type your answer instead.')
      return
    }
    let stream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch {
      setError('Microphone access was blocked. Allow it in your browser settings, or type your answer.')
      return
    }
    streamRef.current = stream
    const chunks = []
    const recorder = new window.MediaRecorder(stream, { mimeType: type.mime })
    recorderRef.current = recorder

    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) chunks.push(e.data)
    }
    recorder.onstop = () => {
      cleanup()
      setRecording(false)
      const blob = new Blob(chunks, { type: type.mime.split(';')[0] })
      if (blob.size > 0) onFinishedRef.current?.(blob, `answer.${type.ext}`)
    }

    const startedAt = Date.now()
    setElapsed(0)
    recorder.start()
    setRecording(true)
    timerRef.current = setInterval(() => setElapsed((Date.now() - startedAt) / 1000), 250)
    stopTimeoutRef.current = setTimeout(stop, maxSeconds * 1000)
  }, [cleanup, maxSeconds, stop])

  useEffect(() => () => {
    const recorder = recorderRef.current
    if (recorder && recorder.state !== 'inactive') {
      recorder.onstop = null
      recorder.stop()
    }
    cleanup()
  }, [cleanup])

  return { recording, elapsed, error, start, stop }
}
