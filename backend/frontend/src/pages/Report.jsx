import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Printer } from 'lucide-react'
import { api } from '../api/client.js'
import EvaluationPanel from '../components/EvaluationPanel.jsx'
import usePageTitle from '../hooks/usePageTitle.js'
import ScoreChart from '../components/ScoreChart.jsx'
import {
  DIFFICULTY_LABELS,
  QUESTION_TYPE_LABELS,
  formatDateTime,
  formatScore,
  formatSeconds,
  humanize,
} from '../lib/format.js'

export default function Report() {
  const { id } = useParams()
  usePageTitle('Interview report')
  const [report, setReport] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    api
      .getReport(id)
      .then((data) => !cancelled && setReport(data))
      .catch((err) => !cancelled && setError(err))
    return () => {
      cancelled = true
    }
  }, [id])

  // A report belongs to whoever owns the interview. For an account that is a session;
  // for a guest interview the id is the only key, so those links keep working.
  if (error?.status === 401) {
    return (
      <div className="container narrow section">
        <h1>Sign in to view this report</h1>
        <p className="muted">
          This report belongs to an account. Sign in with the account that took the interview.
        </p>
        <p>
          <Link to="/login" className="btn btn-primary">Sign in</Link>{' '}
          <Link to="/guest" className="btn btn-secondary">Continue as guest</Link>
        </p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="container narrow section">
        <h1>Report not available</h1>
        <div className="alert alert-error" role="alert">{error.message}</div>
        <p><Link to="/">Back to home</Link></p>
      </div>
    )
  }
  if (!report) return <div className="container narrow section"><p className="muted">Loading report</p></div>

  const { interview } = report
  const answersByQuestion = Object.fromEntries(report.answers.map((a) => [a.question_id, a]))
  const questions = [...report.questions].sort((a, b) => a.sequence - b.sequence)
  const scored = report.answers.filter((a) => a.evaluation_status === 'completed' && a.evaluation)
  const average = scored.length ? scored.reduce((sum, a) => sum + a.evaluation.overall_score, 0) / scored.length : null
  const timedOut = questions.filter((q) => q.state === 'timed_out').length
  const chartData = questions.map((q) => {
    const a = answersByQuestion[q.question_id]
    return { label: String(q.sequence), score: a?.evaluation ? a.evaluation.overall_score : null }
  })
  const competencies = Object.values(report.competency || {}).sort((a, b) => a.competency_id.localeCompare(b.competency_id))
  const integrityCounts = Object.entries(report.integrity_summary || {}).filter(([, n]) => n > 0)

  return (
    <div className="container section report">
      <div className="section-head">
        <div>
          <h1>Interview report</h1>
          <p className="muted">
            {interview.topic} &middot; {DIFFICULTY_LABELS[interview.difficulty] || interview.difficulty} start &middot;{' '}
            {formatDateTime(interview.created_at)}
          </p>
        </div>
        <button type="button" className="btn btn-secondary no-print" onClick={() => window.print()}>
          <Printer size={16} aria-hidden="true" /> Print or save as PDF
        </button>
      </div>

      {interview.status !== 'completed' && (
        <div className="alert alert-warn no-print" role="status">
          This interview is still in progress. <Link to={`/interview/${interview.interview_id}`}>Continue it</Link>
        </div>
      )}

      <dl className="summary">
        <div><dt>Average score</dt><dd>{average === null ? 'Not scored' : `${average.toFixed(1)} / 10`}</dd></div>
        <div><dt>Questions answered</dt><dd>{report.answers.length} of {interview.question_count}</dd></div>
        <div><dt>Scored</dt><dd>{scored.length}</dd></div>
        <div><dt>Ran out of time</dt><dd>{timedOut}</dd></div>
      </dl>

      {questions.length > 0 && (
        <section className="report-section">
          <h2>Score per question</h2>
          <ScoreChart data={chartData} />
        </section>
      )}

      {competencies.length > 0 && (
        <section className="report-section">
          <h2>Estimated level by area</h2>
          <p className="muted small">
            A rough estimate from 0 to 1 that starts at 0.50 and moves 15% of the way toward each answer&apos;s score.
            It reflects this interview only.
          </p>
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Area</th>
                <th scope="col">Estimated level</th>
                <th scope="col">Questions</th>
              </tr>
            </thead>
            <tbody>
              {competencies.map((c) => (
                <tr key={c.competency_id}>
                  <td>{c.competency_id}</td>
                  <td>
                    <span className="meter meter-inline" aria-hidden="true">
                      <span className="meter-fill" style={{ width: `${c.theta * 100}%` }} />
                    </span>
                    {c.theta.toFixed(2)}
                  </td>
                  <td>{c.questions_attempted}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <section className="report-section">
        <h2>Questions and answers</h2>
        {questions.map((q) => {
          const a = answersByQuestion[q.question_id]
          return (
            <article key={q.question_id} className="qa">
              <p className="question-meta">
                <span className="tag">Question {q.sequence}</span>
                {q.question_type && <span className="tag">{QUESTION_TYPE_LABELS[q.question_type] || q.question_type}</span>}
                {q.difficulty && <span className="tag">{DIFFICULTY_LABELS[q.difficulty] || q.difficulty}</span>}
              </p>
              <h3>{q.question_text || q.question_id}</h3>

              {!a && <p className="muted">{q.state === 'timed_out' ? 'No answer: time ran out.' : 'Not answered.'}</p>}

              {a && (
                <>
                  <h4>Your answer</h4>
                  <p className="answer-text">{a.answer_text}</p>
                  <p className="muted small">
                    {a.answer_source === 'voice' ? 'Spoken, then edited' : 'Typed'} &middot; took {formatSeconds(a.elapsed_seconds)} of{' '}
                    {formatSeconds(a.time_limit_seconds)}
                    {a.timed_out && ' (sent during the extra time)'}
                  </p>
                  {a.evaluation_status === 'completed' && a.evaluation ? (
                    <EvaluationPanel evaluation={a.evaluation} competencyUpdate={a.competency_update} />
                  ) : (
                    <p className="muted">Score: {formatScore(null)}</p>
                  )}
                </>
              )}
            </article>
          )
        })}
      </section>

      <section className="report-section">
        <h2>Session notes</h2>
        <p className="muted small">
          Copy, paste, tab switches and similar events recorded during the interview. They are notes for context, not
          proof of anything, and they did not affect any score.
        </p>
        {integrityCounts.length === 0 ? (
          <p>Nothing was recorded.</p>
        ) : (
          <table className="table table-compact">
            <thead>
              <tr><th scope="col">Event</th><th scope="col">Count</th></tr>
            </thead>
            <tbody>
              {integrityCounts.map(([type, count]) => (
                <tr key={type}><td>{humanize(type)}</td><td>{count}</td></tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <p className="muted small">
        Anyone with the link to this page can open it. Share it only with people you want to see your answers.
      </p>
      <p className="no-print"><Link to="/start" className="btn btn-primary">Start another interview</Link></p>
    </div>
  )
}
