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

  async function handleSignOut() {
    setSigningOut(true)
    await signOut()
    navigate('/', { replace: true })
  }

  const name = candidate?.display_name || 'Not set'

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

      <p className="muted small">
        Guest interviews started from this device are not listed here. They stay in your browser on the{' '}
        <Link to="/guest">guest page</Link>.
      </p>
    </div>
  )
}
