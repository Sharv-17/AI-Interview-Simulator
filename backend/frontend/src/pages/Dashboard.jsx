import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client.js'
import usePageTitle from '../hooks/usePageTitle.js'
import { DIFFICULTY_LABELS, formatDateTime } from '../lib/format.js'
import { useSession } from '../lib/session.js'

const STATUS_LABELS = { active: 'In progress', completed: 'Completed' }

export default function Dashboard() {
  usePageTitle('Dashboard')
  const navigate = useNavigate()
  const { user, candidate, signOut } = useSession()
  const [interviews, setInterviews] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [signingOut, setSigningOut] = useState(false)
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

  async function handleSignOut() {
    setSigningOut(true)
    await signOut()
    navigate('/', { replace: true })
  }

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

  return (
    <div className="container section dashboard">
      <div className="section-head">
        <div>
          <h1>Dashboard</h1>
          <p className="muted">
            Signed in as {name}. Your interviews are saved to this account.
          </p>
        </div>
        <div className="dashboard-actions">
          <Link to="/start" className="btn btn-primary">Start an interview</Link>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={handleSignOut}
            disabled={signingOut}
          >
            {signingOut ? 'Signing out' : 'Sign out'}
          </button>
        </div>
      </div>

      <dl className="summary">
        <div>
          <dt>Name</dt>
          <dd>{name}</dd>
        </div>
        <div>
          <dt>Email</dt>
          <dd>{user?.email || ''}</dd>
        </div>
        <div>
          <dt>Email verified</dt>
          <dd>{user?.is_email_verified ? 'Yes' : 'Not yet'}</dd>
        </div>
        <div>
          <dt>Interviews</dt>
          <dd>{loading ? 'Loading' : interviews.length}</dd>
        </div>
      </dl>

      <section className="dashboard-section">
        <h2>Previous interviews</h2>

        {error && (
          <div className="alert alert-error" role="alert">{error}</div>
        )}

        {!error && loading && <p className="muted">Loading your interviews</p>}

        {!error && !loading && interviews.length === 0 && (
          <p className="muted">
            No interviews yet. <Link to="/start">Start your first one</Link>.
          </p>
        )}

        {!error && interviews.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Started</th>
                <th scope="col">Topic</th>
                <th scope="col">Difficulty</th>
                <th scope="col">Questions</th>
                <th scope="col">Status</th>
                <th scope="col"><span className="visually-hidden">Links</span></th>
              </tr>
            </thead>
            <tbody>
              {interviews.map((interview) => (
                <tr key={interview.interview_id}>
                  <td>{formatDateTime(interview.created_at)}</td>
                  <td>{interview.topic}</td>
                  <td>{DIFFICULTY_LABELS[interview.difficulty] || interview.difficulty}</td>
                  <td>{interview.current_question} of {interview.question_count}</td>
                  <td>{STATUS_LABELS[interview.status] || interview.status}</td>
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
        )}
      </section>

      <section className="dashboard-section">
        <h2>Progress</h2>
        <p className="muted small">
          Estimates, not a verdict on your ability: each area is scored from 0 to 1. Every interview starts an
          area at 0.50 and moves 15% of the way toward each answer&apos;s score, so these estimates belong to a
          single interview and do not carry over between interviews. The level shown is from your most recent
          interview that covered the area, and the change is the movement inside that interview.
        </p>

        {historyError && (
          <div className="alert alert-error" role="alert">
            Could not load your progress: {historyError}
          </div>
        )}

        {!historyError && historyLoading && <p className="muted">Loading your progress</p>}

        {!historyError && !historyLoading && progress.length === 0 && (
          <p className="muted">
            Nothing scored yet. <Link to="/start">Start an interview</Link> and your estimated levels will appear
            here.
          </p>
        )}

        {!historyError && !historyLoading && progress.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Area</th>
                <th scope="col">Latest estimated level</th>
                <th scope="col">Answers scored</th>
                <th scope="col">Change in that interview</th>
              </tr>
            </thead>
            <tbody>
              {progress.map((area) => (
                <tr key={area.competency_id}>
                  <td>{area.competency_id}</td>
                  <td>
                    <span className="meter meter-inline" aria-hidden="true">
                      <span className="meter-fill" style={{ width: `${area.theta * 100}%` }} />
                    </span>
                    {area.theta.toFixed(2)}
                  </td>
                  <td>{area.answers}</td>
                  <td>
                    {area.change === null ? (
                      <span title="At least two scored answers in one interview are needed to show movement.">
                        —
                      </span>
                    ) : (
                      `${area.change >= 0 ? '+' : ''}${area.change.toFixed(2)}`
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {!historyError && scoredAnswers > 0 && (
          <p className="muted small">
            {scoredAnswers === 1
              ? '1 scored answer so far. One answer is not a trend, so no change is shown yet.'
              : `${scoredAnswers} scored answers across your interviews so far.`}
          </p>
        )}
      </section>

      <p className="muted small">
        Guest interviews started from this device are not listed here. They stay in your browser on the{' '}
        <Link to="/guest">guest page</Link>.
      </p>
    </div>
  )
}
