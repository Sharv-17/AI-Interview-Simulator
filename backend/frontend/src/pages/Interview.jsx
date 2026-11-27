import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Mic, Square } from 'lucide-react'
import { api } from '../api/client.js'
import EvaluationPanel from '../components/EvaluationPanel.jsx'
import { useCountdown } from '../hooks/useCountdown.js'
import { useIntegrityMonitor } from '../hooks/useIntegrityMonitor.js'
import { useVoiceRecorder, voiceSupported } from '../hooks/useVoiceRecorder.js'
import usePageTitle from '../hooks/usePageTitle.js'
import { DIFFICULTY_LABELS, QUESTION_TYPE_LABELS, formatClock } from '../lib/format.js'
import { MAX_ANSWER_CHARS, MAX_RECORDING_SECONDS } from '../siteConfig.js'

const CODING_LANGUAGES = [
  { value: 'python', label: 'Python' },
  { value: 'javascript', label: 'JavaScript' },
  { value: 'java', label: 'Java' },
  { value: 'cpp', label: 'C++' },
]

// Turns the server's timing fields into local Date.now() deadlines.
function computeDeadlines(data) {
  if (data.next_action !== 'answer' || data.seconds_remaining == null) return { nominal: null, hard: null }
  const now = Date.now()
  const grace = (data.grace_seconds || 0) * 1000
  if (data.seconds_remaining > 0) {
    const nominal = now + data.seconds_remaining * 1000
    return { nominal, hard: nominal + grace }
  }
  // Already inside the grace period: estimate what is left from the server deadline.
  const left = data.deadline_at ? new Date(data.deadline_at).getTime() - now : 0
  return { nominal: now, hard: now + Math.min(Math.max(left, 0), grace) }
}

export default function Interview() {
  const { id } = useParams()
  usePageTitle('Interview')
  const navigate = useNavigate()

  const [interview, setInterview] = useState(null)
  const [question, setQuestion] = useState(null)
  const [loadError, setLoadError] = useState('')
  const [deadlines, setDeadlines] = useState({ nominal: null, hard: null })

  const [answer, setAnswer] = useState('')
  const [language, setLanguage] = useState('python')
  const [usedVoice, setUsedVoice] = useState(false)
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState('')
  const [transcribing, setTranscribing] = useState(false)
  const [voiceError, setVoiceError] = useState('')

  const questionIdRef = useRef(null)
  const autoSubmitted = useRef(false)
  const expiryHandled = useRef(false)

  const answering = interview?.next_action === 'answer'
  const integrity = useIntegrityMonitor(answering)
  const { reset: resetIntegrity, drain: drainIntegrity, recordCopy, recordPaste } = integrity

  const nominalLeft = useCountdown(deadlines.nominal)
  const hardLeft = useCountdown(deadlines.hard)

  // ---- loading -----------------------------------------------------------------

  const applyInterview = useCallback(
    async (data) => {
      if (data.status === 'completed' || data.next_action === 'completed') {
        navigate(`/report/${id}`, { replace: true })
        return
      }
      if (data.current_question_id && data.current_question_id !== questionIdRef.current) {
        const q = await api.getQuestion(data.current_question_id)
        questionIdRef.current = data.current_question_id
        setQuestion(q)
        setAnswer('')
        setUsedVoice(false)
        setResult(null)
        setActionError('')
        setVoiceError('')
        autoSubmitted.current = false
        expiryHandled.current = false
        resetIntegrity()
      }
      setInterview(data)
      setDeadlines(computeDeadlines(data))

      // Coming back to a question that was already scored: fetch its stored result.
      // retry-evaluation is idempotent for scored answers and does not re-run the evaluator.
      if (data.next_action === 'advance' && data.question_state === 'evaluated') {
        try {
          const stored = await api.retryEvaluation(id, data.current_question_id)
          setResult((current) => current || stored)
        } catch {
          // Not critical: the person can still move on.
        }
      }
    },
    [id, navigate, resetIntegrity],
  )

  const refresh = useCallback(async () => {
    const data = await api.getInterview(id)
    await applyInterview(data)
  }, [id, applyInterview])

  useEffect(() => {
    let cancelled = false
    Promise.resolve()
      .then(refresh)
      .catch((err) => !cancelled && setLoadError(err))
    return () => {
      cancelled = true
    }
  }, [refresh])

  // Warn before leaving with an unsent answer.
  useEffect(() => {
    if (!answering || !answer.trim()) return undefined
    const handler = (e) => {
      e.preventDefault()
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [answering, answer])

  // ---- integrity events ----------------------------------------------------------

  const flushEvents = useCallback(
    async (events) => {
      const questionId = questionIdRef.current
      for (let i = 0; i < events.length; i += 50) {
        try {
          await api.reportIntegrityEvents(id, questionId, events.slice(i, i + 50))
        } catch {
          // Indicators are best effort and never block the interview.
        }
      }
    },
    [id],
  )

  // ---- actions -------------------------------------------------------------------

  const submit = useCallback(
    async (reason) => {
      const text = answer.trim()
      if (!text) {
        setActionError('Write or record an answer before submitting.')
        return
      }
      setBusy(true)
      setActionError('')
      const all = drainIntegrity()
      const attached = all.slice(0, 50)
      if (all.length > 50) await flushEvents(all.slice(50))

      try {
        const response = await api.submitAnswer(id, {
          question_id: questionIdRef.current,
          answer_text: text,
          answer_source: usedVoice ? 'voice' : 'text',
          language: question?.question_type === 'coding' ? language : undefined,
          submission_reason: reason,
          integrity_events: attached,
        })
        setResult(response)
        await refresh()
      } catch (err) {
        await flushEvents(attached)
        setActionError(err.message)
        if (err.status === 409) await refresh().catch(() => {})
      } finally {
        setBusy(false)
      }
    },
    [answer, drainIntegrity, flushEvents, id, language, question, refresh, usedVoice],
  )

  async function retryEvaluation() {
    setBusy(true)
    setActionError('')
    try {
      const response = await api.retryEvaluation(id, questionIdRef.current)
      setResult(response)
      await refresh()
    } catch (err) {
      setActionError(err.message)
      if (err.status === 409) await refresh().catch(() => {})
    } finally {
      setBusy(false)
    }
  }

  async function goNext() {
    setBusy(true)
    setActionError('')
    try {
      const data = await api.advance(id)
      await applyInterview(data)
      window.scrollTo(0, 0)
    } catch (err) {
      setActionError(err.message)
    } finally {
      setBusy(false)
    }
  }

  // ---- voice ----------------------------------------------------------------------

  const handleRecording = useCallback(
    async (blob, filename) => {
      setTranscribing(true)
      setVoiceError('')
      try {
        const res = await api.transcribe(id, questionIdRef.current, blob, filename)
        const transcript = (res.transcript || '').trim()
        if (transcript) {
          setAnswer((prev) => (prev.trim() ? `${prev.trimEnd()} ${transcript}` : transcript).slice(0, MAX_ANSWER_CHARS))
          setUsedVoice(true)
        }
      } catch (err) {
        setVoiceError(err.message)
        if (err.code === 'question_deadline_passed') await refresh().catch(() => {})
      } finally {
        setTranscribing(false)
      }
    },
    [id, refresh],
  )

  const recorder = useVoiceRecorder({ maxSeconds: MAX_RECORDING_SECONDS, onFinished: handleRecording })
  const { stop: stopRecording } = recorder
  const canRecord = voiceSupported()

  // ---- timer side effects -----------------------------------------------------------

  // Nominal time is up: send what has been written, if anything (it is still inside the grace period).
  useEffect(() => {
    if (!answering || nominalLeft !== 0 || autoSubmitted.current || busy) return
    if (recorder.recording || transcribing) return
    if (!answer.trim()) return
    // One-shot action, guarded by the ref. Not cancelled on re-render on purpose.
    autoSubmitted.current = true
    setTimeout(() => submit('timeout'), 0)
  }, [answering, nominalLeft, busy, answer, submit, recorder.recording, transcribing])

  // Grace period over: the server has closed the question. Reload to get its new state.
  useEffect(() => {
    if (!answering || hardLeft !== 0 || expiryHandled.current || busy) return
    expiryHandled.current = true
    stopRecording()
    const events = drainIntegrity()
    // One-shot action, guarded by the ref. Not cancelled on re-render on purpose.
    setTimeout(async () => {
      await flushEvents(events)
      refresh().catch((err) => setActionError(err.message))
    }, 1500)
  }, [answering, hardLeft, busy, drainIntegrity, flushEvents, refresh, stopRecording])

  // ---- render ---------------------------------------------------------------------

  // An account-owned interview answers 401 without its owner's session. Guest
  // interviews never do, so they keep opening from a direct link as before.
  if (loadError?.status === 401) {
    return (
      <div className="container narrow section">
        <h1>Sign in to continue this interview</h1>
        <p className="muted">
          This interview belongs to an account. Sign in with the account that started it to pick it up where
          you left off.
        </p>
        <p>
          <Link to="/login" state={{ from: `/interview/${id}` }} className="btn btn-primary">Sign in</Link>{' '}
          <Link to="/guest" className="btn btn-secondary">Continue as guest</Link>
        </p>
      </div>
    )
  }

  if (loadError) {
    return (
      <div className="container narrow section">
        <h1>Interview not available</h1>
        <div className="alert alert-error" role="alert">{loadError.message}</div>
        <p><Link to="/start">Start a new interview</Link></p>
      </div>
    )
  }

  if (!interview) {
    return <div className="container narrow section"><p className="muted">Loading interview</p></div>
  }

  if (interview.next_action === 'none' || !question) {
    return (
      <div className="container narrow section">
        <h1>No question available</h1>
        <p>
          No question could be found for the topic &quot;{interview.topic}&quot;. Try a different topic.
        </p>
        <p><Link to="/start" className="btn btn-primary">Choose another topic</Link></p>
      </div>
    )
  }

  const isLast = interview.current_question >= interview.question_count
  const isCoding = question.question_type === 'coding'
  const inGrace = answering && nominalLeft === 0 && hardLeft > 0
  const evaluation = result?.evaluation

  return (
    <div className="container section interview-page">
      <aside className="interview-rail">
      <div className="interview-bar">
        <p className="progress-text">
          <span className="muted">{interview.topic}:</span> question {interview.current_question} of{' '}
          {interview.question_count}
        </p>
        {answering && nominalLeft !== null && (
          <div className={`timer ${nominalLeft <= 15 ? 'timer-warn' : ''} ${inGrace ? 'timer-over' : ''}`} role="timer" aria-live="off">
            {inGrace ? `Over time: ${formatClock(hardLeft)} to submit` : formatClock(nominalLeft)}
          </div>
        )}
      </div>
      <div
        className="progress"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={interview.question_count}
        aria-valuenow={interview.current_question - 1}
        aria-label="Questions completed"
      >
        <span style={{ width: `${((interview.current_question - 1) / interview.question_count) * 100}%` }} />
      </div>
      </aside>

      <div className="interview-main">
      <section className="question-card margined" aria-labelledby="question-text">
        <span className="margin-number" aria-hidden="true">{interview.current_question}.</span>
        <p className="question-meta">
          <span className="tag">{QUESTION_TYPE_LABELS[question.question_type] || question.question_type}</span>
          <span className="tag">{DIFFICULTY_LABELS[question.difficulty] || question.difficulty}</span>
          <span className="muted small">{question.competency}</span>
        </p>
        <h1 id="question-text" className="question-text">{question.question_text}</h1>
      </section>

      {answering && (
        <form
          className="answer-form"
          onSubmit={(e) => {
            e.preventDefault()
            submit(nominalLeft === 0 ? 'timeout' : 'candidate_submitted')
          }}
        >
          {inGrace && (
            <div className="alert alert-warn" role="status">
              Time is up for this question. You can still submit what you have before the extra time runs out.
            </div>
          )}

          {isCoding && (
            <div className="field field-inline">
              <label htmlFor="language">Language</label>
              <select id="language" value={language} onChange={(e) => setLanguage(e.target.value)}>
                {CODING_LANGUAGES.map((l) => (
                  <option key={l.value} value={l.value}>{l.label}</option>
                ))}
              </select>
            </div>
          )}

          <div className="field">
            <label htmlFor="answer">Your answer</label>
            <textarea
              id="answer"
              className={isCoding ? 'code-input' : ''}
              rows={isCoding ? 14 : 9}
              value={answer}
              maxLength={MAX_ANSWER_CHARS}
              onChange={(e) => setAnswer(e.target.value)}
              onCopy={recordCopy}
              onPaste={recordPaste}
              disabled={busy}
              spellCheck={!isCoding}
              placeholder={isCoding ? 'Write your code here' : 'Type your answer, or record it below and edit the transcript'}
            />
            <p className="field-help">
              {answer.length.toLocaleString()} / {MAX_ANSWER_CHARS.toLocaleString()} characters
              {usedVoice && '. Includes a voice transcript, so check it before submitting.'}
            </p>
          </div>

          {canRecord && !isCoding && (
            <div className="voice">
              {recorder.recording ? (
                <button type="button" className="btn btn-secondary" onClick={recorder.stop}>
                  <Square size={16} aria-hidden="true" /> Stop recording ({formatClock(recorder.elapsed)} / {formatClock(MAX_RECORDING_SECONDS)})
                </button>
              ) : (
                <button type="button" className="btn btn-secondary" onClick={recorder.start} disabled={busy || transcribing}>
                  <Mic size={16} aria-hidden="true" /> {transcribing ? 'Transcribing' : 'Record answer'}
                </button>
              )}
              <p className="field-help">
                Up to {MAX_RECORDING_SECONDS} seconds per recording. The audio is turned into text and then discarded;
                only the text you submit is saved.
              </p>
              {(recorder.error || voiceError) && (
                <div className="alert alert-error" role="alert">{recorder.error || voiceError}</div>
              )}
            </div>
          )}

          {actionError && <div className="alert alert-error" role="alert">{actionError}</div>}

          <div className="actions">
            <button type="submit" className="btn btn-primary" disabled={busy || recorder.recording || transcribing}>
              {busy ? 'Scoring your answer' : 'Submit answer'}
            </button>
          </div>

          <p className="muted small integrity-note">
            While you answer, this page notes when you copy, paste, switch tabs or leave the window. It never reads
            your clipboard. These notes appear in your report and do not change your score.
          </p>
        </form>
      )}

      {interview.next_action === 'retry_evaluation' && (
        <section className="result-card">
          <h2>Your answer is saved but not scored yet</h2>
          <p>The scoring service did not return a result. Your answer is safe. Try scoring it again in a moment.</p>
          {actionError && <div className="alert alert-error" role="alert">{actionError}</div>}
          <div className="actions">
            <button type="button" className="btn btn-primary" onClick={retryEvaluation} disabled={busy}>
              {busy ? 'Trying again' : 'Try scoring again'}
            </button>
          </div>
        </section>
      )}

      {interview.next_action === 'advance' && (
        <section className="result-card">
          {/* After a missed deadline the backend reports state "active" (or "timed_out") with action "advance". */}
          {(interview.question_state === 'timed_out' || interview.question_state === 'active') && (
            <>
              <h2>Time ran out</h2>
              <p>No answer was received for this question before the time limit.</p>
            </>
          )}
          {interview.question_state === 'evaluation_failed' && (
            <>
              <h2>This answer could not be scored</h2>
              <p>Your answer is saved, but scoring failed after several attempts. It will show as not scored in your report.</p>
            </>
          )}
          {interview.question_state === 'evaluated' && (
            <>
              <h2>Your score</h2>
              {evaluation ? (
                <EvaluationPanel evaluation={evaluation} competencyUpdate={result?.competency_update} />
              ) : (
                <p className="muted">Your answer was scored. The details are in your report.</p>
              )}
            </>
          )}

          {actionError && <div className="alert alert-error" role="alert">{actionError}</div>}
          <div className="actions">
            <button type="button" className="btn btn-primary" onClick={goNext} disabled={busy}>
              {busy ? 'Loading' : isLast ? 'Finish and see report' : 'Next question'}
            </button>
          </div>
        </section>
      )}
      </div>
    </div>
  )
}
