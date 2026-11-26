import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { FileText, Gauge, ListChecks, Timer } from 'lucide-react'
import { api } from '../api/client.js'
import { DIFFICULTY_LABELS, formatDateTime } from '../lib/format.js'
import usePageTitle from '../hooks/usePageTitle.js'
import { clearRecentSessions, loadRecentSessions } from '../lib/recentSessions.js'

const STEPS = [
  {
    icon: ListChecks,
    title: 'Choose a topic and difficulty',
    text: 'Pick a subject, a starting difficulty, and how many questions you want (1 to 20).',
  },
  {
    icon: Timer,
    title: 'Answer each question on the clock',
    text: 'Every question has its own time limit. Type your answer, or record it and edit the transcript before you submit.',
  },
  {
    icon: Gauge,
    title: 'Get scored after every answer',
    text: 'An AI model scores your answer on accuracy, relevance, completeness, clarity and understanding, and lists what you missed. The next question is picked based on how you are doing.',
  },
  {
    icon: FileText,
    title: 'Review the full report',
    text: 'At the end you see every question, your answer, its score and feedback, and your estimated level in each area.',
  },
]

export default function Home() {
  usePageTitle('')
  const [topics, setTopics] = useState([])
  const [recent, setRecent] = useState(() => loadRecentSessions())

  useEffect(() => {
    let cancelled = false
    api
      .listQuestions()
      .then((questions) => {
        if (!cancelled) setTopics([...new Set(questions.map((q) => q.topic))].sort())
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <>
      <section className="hero">
        <div className="container hero-inner">
          <h1>Practice technical interviews that adjust to your answers.</h1>
          <p className="lead">
            Answer software engineering questions against a timer, by typing or speaking. Each answer is scored
            with written feedback, and the next question depends on how well you did.
          </p>
          <div className="actions">
            <Link to="/start" className="btn btn-primary">Start an interview</Link>
          </div>
          <p className="muted small">No account needed. Scores come from an AI model and can be wrong.</p>
        </div>
      </section>

      <section className="section">
        <div className="container">
          <h2>How it works</h2>
          <ol className="steps">
            {STEPS.map(({ icon: Icon, title, text }) => (
              <li key={title} className="step">
                <Icon className="step-icon" size={20} strokeWidth={1.75} aria-hidden="true" />
                <h3>{title}</h3>
                <p>{text}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {topics.length > 0 && (
        <section className="section section-alt">
          <div className="container">
            <h2>Topics you can practice</h2>
            <ul className="topic-list">
              {topics.map((topic) => (
                <li key={topic}>
                  <Link to={`/start?topic=${encodeURIComponent(topic)}`}>{topic}</Link>
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}

      {recent.length > 0 && (
        <section className="section">
          <div className="container">
            <div className="section-head">
              <h2>Your recent interviews on this device</h2>
              <button
                type="button"
                className="btn btn-link"
                onClick={() => {
                  clearRecentSessions()
                  setRecent([])
                }}
              >
                Clear list
              </button>
            </div>
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Started</th>
                  <th scope="col">Topic</th>
                  <th scope="col">Difficulty</th>
                  <th scope="col">Questions</th>
                  <th scope="col"><span className="visually-hidden">Links</span></th>
                </tr>
              </thead>
              <tbody>
                {recent.map((s) => (
                  <tr key={s.id}>
                    <td>{formatDateTime(s.startedAt)}</td>
                    <td>{s.topic}</td>
                    <td>{DIFFICULTY_LABELS[s.difficulty] || s.difficulty}</td>
                    <td>{s.questionCount}</td>
                    <td className="table-links">
                      <Link to={`/interview/${s.id}`}>Continue</Link>
                      <Link to={`/report/${s.id}`}>Report</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  )
}
