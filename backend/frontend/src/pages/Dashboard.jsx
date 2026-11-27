import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client.js'
import usePageTitle from '../hooks/usePageTitle.js'
import { DIFFICULTY_LABELS, formatDateTime } from '../lib/format.js'
import { useSession } from '../lib/session.js'

const STATUS_LABELS = { active: 'In progress', completed: 'Completed' }

export default function Dashboard() {
  usePageTitle('Dashboard')
  const { user, candidate } = useSession()
  const [interviews, setInterviews] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [history, setHistory] = useState([])
  const [historyLoading, setHistoryLoading] = useState(true)
  const [historyError, setHistoryError] = useState('')

  // Real history from the server, scoped to this account's candidate.
  useEffect(() => {
    let cancelled = false
    api.auth
      .interviews()
      .then((list) => {
        if (!cancelled) setInterviews(Array.isArray(list) ? list : [])
      })
      .catch((err) => {
        if (!cancelled) setError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Every scored answer on this account, oldest first. The server only serves this for
  // the signed-in owner, which is what makes progress tracking an account benefit.
  useEffect(() => {
    const candidateId = candidate?.candidate_id
    if (!candidateId) return undefined
    let cancelled = false
    api.auth
      .competencyHistory(candidateId)
      .then((entries) => {
        if (!cancelled) setHistory(Array.isArray(entries) ? entries : [])
      })
      .catch((err) => {
        // Progress is a bonus view: show the failure in its own section rather than
        // hiding the dashboard, and never let it look like "no data".
        if (!cancelled) setHistoryError(err.message)
      })
      .finally(() => {
        if (!cancelled) setHistoryLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [candidate?.candidate_id])

  const name = candidate?.display_name || 'Not set'

  // The backend keeps competency state per interview and starts every area at 0.50, so a
  // theta cannot be compared across interviews. Entries arrive oldest first (ordered by
  // recorded_at), so per area we keep the most recently practised interview and measure
  // movement only inside it.
  const areas = new Map()
  for (const entry of history) {
    const area = areas.get(entry.competency_id) || { total: 0, interviews: new Map() }
    area.total += 1
    const run = area.interviews.get(entry.interview_id) || []
    run.push(entry)
    area.interviews.set(entry.interview_id, run)
    areas.set(entry.competency_id, area)
  }

  const progress = [...areas.entries()]
    .map(([competencyId, area]) => {
      const runs = [...area.interviews.values()]
      const run = runs[runs.length - 1]
      const theta = run[run.length - 1].new_theta
      return {
        competency_id: competencyId,
        theta,
        answers: area.total,
        // One answer moves the estimate toward that score; it is not a trend.
        change: run.length >= 2 ? theta - run[0].previous_theta : null,
      }
    })
    .sort((a, b) => a.competency_id.localeCompare(b.competency_id))
  const scoredAnswers = history.length

  const completed = interviews.filter((item) => item.status === 'completed').length
  const inProgress = interviews.filter((item) => item.status === 'active').length

  return (
    <div className="container section dashboard">
      <header className="dash-head">
        <div className="dash-identity">
          <h1>Dashboard</h1>
          <p className="dash-account">
            <span className="dash-name">{name}</span>
            {user?.email && <span className="dash-email">{user.email}</span>}
          </p>
        </div>
        <Link to="/start" className="btn btn-primary">Start an interview</Link>
      </header>

      <dl className="stats" aria-busy={loading || historyLoading}>
        <div>
          <dt>Interviews started</dt>
          <dd>{loading ? '-' : interviews.length}</dd>
        </div>
        <div>
          <dt>Completed</dt>
          <dd>{loading ? '-' : completed}</dd>
        </div>
        <div>
          <dt>In progress</dt>
          <dd>{loading ? '-' : inProgress}</dd>
        </div>
        <div>
          <dt>Answers scored</dt>
          <dd>{historyLoading && !historyError ? '-' : scoredAnswers}</dd>
        </div>
      </dl>

      <section className="panel" aria-labelledby="interviews-heading">
        <div className="panel-head">
          <h2 id="interviews-heading">Your interviews</h2>
        </div>

        {error && <div className="alert alert-error" role="alert">{error}</div>}
        {!error && loading && <p className="muted">Loading your interviews</p>}

        {!error && !loading && interviews.length === 0 && (
          <div className="empty-state">
            <p>You have not started an interview yet. Your interviews and reports will be listed here.</p>
            <Link to="/start" className="btn btn-secondary">Start your first interview</Link>
          </div>
        )}

        {!error && interviews.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Started</th>
                  <th scope="col">Topic</th>
                  <th scope="col">Difficulty</th>
                  <th scope="col">Question</th>
                  <th scope="col">Status</th>
                  <th scope="col"><span className="visually-hidden">Links</span></th>
                </tr>
              </thead>
              <tbody>
                {interviews.map((interview) => (
                  <tr key={interview.interview_id}>
                    <td className="nowrap">{formatDateTime(interview.created_at)}</td>
                    <td>{interview.topic}</td>
                    <td>{DIFFICULTY_LABELS[interview.difficulty] || interview.difficulty}</td>
                    <td className="nowrap">{interview.current_question} of {interview.question_count}</td>
                    <td>
                      <span className={`status status-${interview.status}`}>
                        {STATUS_LABELS[interview.status] || interview.status}
                      </span>
                    </td>
                    <td className="table-links">
                      {interview.status === 'active' && (
                        <Link to={`/interview/${interview.interview_id}`}>Continue</Link>
                      )}
                      <Link to={`/report/${interview.interview_id}`}>Report</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="panel" aria-labelledby="progress-heading">
        <div className="panel-head">
          <h2 id="progress-heading">Progress by area</h2>
          <p className="muted small">
            Your estimated level in each area, from 0 to 1, taken from the most recent interview that covered it.
          </p>
        </div>

        {historyError && (
          <div className="alert alert-error" role="alert">
            Could not load your progress: {historyError}
          </div>
        )}
        {!historyError && historyLoading && <p className="muted">Loading your progress</p>}

        {!historyError && !historyLoading && progress.length === 0 && (
          <div className="empty-state">
            <p>Nothing scored yet. Finish a few questions and your estimated level in each area will appear here.</p>
          </div>
        )}

        {!historyError && !historyLoading && progress.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Area</th>
                  <th scope="col">Estimated level</th>
                  <th scope="col">Answers scored</th>
                  <th scope="col">Change in that interview</th>
                </tr>
              </thead>
              <tbody>
                {progress.map((area) => (
                  <tr key={area.competency_id}>
                    <td>{area.competency_id}</td>
                    <td className="nowrap">
                      <span className="meter meter-inline" aria-hidden="true">
                        <span className="meter-fill" style={{ width: `${area.theta * 100}%` }} />
                      </span>
                      {area.theta.toFixed(2)}
                    </td>
                    <td>{area.answers}</td>
                    <td>
                      {area.change === null ? (
                        <span className="muted small">Needs 2 or more answers</span>
                      ) : (
                        `${area.change >= 0 ? '+' : ''}${area.change.toFixed(2)}`
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <details className="explainer">
          <summary>How is this estimated?</summary>
          <p>
            Each interview starts every area at 0.50. After each scored answer, the estimate moves 15% of the way
            toward that answer&apos;s score. Estimates are kept per interview and do not carry over between
            interviews, so the change column shows movement inside the most recent interview only. These are rough
            estimates, not a verdict on your ability.
          </p>
        </details>
      </section>

      <p className="muted small">
        Guest interviews started on this device are not saved to your account. You can find them on the{' '}
        <Link to="/guest">guest page</Link>.
      </p>
    </div>
  )
}
