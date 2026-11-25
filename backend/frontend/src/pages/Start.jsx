import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api/client.js'
import usePageTitle from '../hooks/usePageTitle.js'
import { saveRecentSession } from '../lib/recentSessions.js'

const DIFFICULTIES = [
  { value: 'easy', label: 'Easy', hint: 'Definitions and core ideas' },
  { value: 'medium', label: 'Medium', hint: 'Trade-offs and applied questions' },
  { value: 'hard', label: 'Hard', hint: 'Design, edge cases and deeper reasoning' },
]

export default function Start() {
  usePageTitle('Start an interview')
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [topics, setTopics] = useState([])
  const [loadError, setLoadError] = useState('')
  const [topic, setTopic] = useState(params.get('topic') || '')
  const [difficulty, setDifficulty] = useState('medium')
  const [questionCount, setQuestionCount] = useState(5)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    api
      .listQuestions()
      .then((questions) => {
        if (cancelled) return
        const list = [...new Set(questions.map((q) => q.topic))].sort()
        setTopics(list)
        setTopic((current) => (list.includes(current) ? current : list[0] || ''))
      })
      .catch((err) => {
        if (!cancelled) setLoadError(err.message)
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    const count = Number(questionCount)
    if (!topic) return setError('Choose a topic.')
    if (!Number.isInteger(count) || count < 1 || count > 20) {
      return setError('Number of questions must be a whole number from 1 to 20.')
    }
    setSubmitting(true)
    try {
      const interview = await api.startInterview({ topic, difficulty, questionCount: count })
      saveRecentSession({
        id: interview.interview_id,
        topic: interview.topic,
        difficulty: interview.difficulty,
        questionCount: interview.question_count,
        startedAt: new Date().toISOString(),
      })
      navigate(`/interview/${interview.interview_id}`)
    } catch (err) {
      setError(err.message)
      setSubmitting(false)
    }
  }

  return (
    <div className="container narrow section">
      <h1>Start an interview</h1>
      <p className="lead">
        The timer for the first question starts as soon as you press Start, so get ready first.
      </p>

      {loadError && (
        <div className="alert alert-error" role="alert">
          Could not load topics: {loadError}
        </div>
      )}

      <form className="form" onSubmit={handleSubmit} noValidate>
        <div className="field">
          <label htmlFor="topic">Topic</label>
          <select id="topic" value={topic} onChange={(e) => setTopic(e.target.value)} disabled={topics.length === 0}>
            {topics.length === 0 && <option value="">Loading topics</option>}
            {topics.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>

        <fieldset className="field">
          <legend>Starting difficulty</legend>
          <div className="choice-group">
            {DIFFICULTIES.map((d) => (
              <label key={d.value} className={`choice ${difficulty === d.value ? 'is-selected' : ''}`}>
                <input
                  type="radio"
                  name="difficulty"
                  value={d.value}
                  checked={difficulty === d.value}
                  onChange={() => setDifficulty(d.value)}
                />
                <span className="choice-label">{d.label}</span>
                <span className="choice-hint">{d.hint}</span>
              </label>
            ))}
          </div>
          <p className="field-help">Later questions can be easier or harder depending on your answers.</p>
        </fieldset>

        <div className="field">
          <label htmlFor="count">Number of questions</label>
          <input
            id="count"
            type="number"
            min="1"
            max="20"
            step="1"
            inputMode="numeric"
            value={questionCount}
            onChange={(e) => setQuestionCount(e.target.value)}
          />
          <p className="field-help">From 1 to 20. Most questions take 1 to 3 minutes.</p>
        </div>

        {error && (
          <div className="alert alert-error" role="alert">{error}</div>
        )}

        <div className="actions">
          <button type="submit" className="btn btn-primary" disabled={submitting || topics.length === 0}>
            {submitting ? 'Starting' : 'Start'}
          </button>
        </div>
      </form>
    </div>
  )
}
