import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { Eye, EyeOff } from 'lucide-react'
import AuthShell from '../components/AuthShell.jsx'
import usePageTitle from '../hooks/usePageTitle.js'
import { authErrorMessage, validateEmail, validateLoginPassword } from '../lib/auth.js'
import { useSession } from '../lib/session.js'

export default function Login() {
  usePageTitle('Sign in')
  const navigate = useNavigate()
  const location = useLocation()
  const { signIn } = useSession()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState({})
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const emailRef = useRef(null)
  const passwordRef = useRef(null)
  const alertRef = useRef(null)

  // Move focus to the notice so mobile users (who submit from below it) see the
  // result without hunting for it. role="alert" still announces it to screen readers.
  useEffect(() => {
    if (error) alertRef.current?.focus()
  }, [error])

  async function handleSubmit(event) {
    event.preventDefault()
    const nextErrors = { email: validateEmail(email), password: validateLoginPassword(password) }
    setErrors(nextErrors)
    setError('')
    if (nextErrors.email) return emailRef.current?.focus()
    if (nextErrors.password) return passwordRef.current?.focus()

    setBusy(true)
    try {
      await signIn({ email: email.trim(), password })
      const target = location.state?.from || '/dashboard'
      navigate(target, { replace: true })
    } catch (err) {
      setError(authErrorMessage(err))
      setBusy(false)
    }
  }

  return (
    <AuthShell>
      <h2>Sign in</h2>
      <p className="auth-sub">Use the email address and password you registered with.</p>

      {error && (
        <div className="alert alert-error" role="alert" tabIndex={-1} ref={alertRef}>
          {error}
        </div>
      )}

      <form className="auth-form" onSubmit={handleSubmit} noValidate>
        <div className="field">
          <label htmlFor="email">Email</label>
          <input
            ref={emailRef}
            id="email"
            name="email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            aria-invalid={Boolean(errors.email)}
            aria-describedby={errors.email ? 'email-error' : undefined}
          />
          {errors.email && (
            <p className="field-error" id="email-error">{errors.email}</p>
          )}
        </div>

        <div className="field">
          <label htmlFor="password">Password</label>
          <div className="password-wrap">
            <input
              ref={passwordRef}
              id="password"
              name="password"
              type={showPassword ? 'text' : 'password'}
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              aria-invalid={Boolean(errors.password)}
              aria-describedby={errors.password ? 'password-error' : undefined}
            />
            <button
              type="button"
              className="password-toggle"
              onClick={() => setShowPassword((visible) => !visible)}
              aria-pressed={showPassword}
              aria-label={showPassword ? 'Hide password' : 'Show password'}
            >
              {showPassword ? (
                <EyeOff size={18} aria-hidden="true" />
              ) : (
                <Eye size={18} aria-hidden="true" />
              )}
            </button>
          </div>
          {errors.password && (
            <p className="field-error" id="password-error">{errors.password}</p>
          )}
        </div>

        <button type="submit" className="btn btn-primary btn-block" disabled={busy}>
          {busy ? 'Signing in' : 'Sign in'}
        </button>
      </form>

      <div className="auth-divider">or</div>

      <Link to="/guest" className="btn btn-secondary btn-block">Continue as guest</Link>
      <p className="auth-guest-note muted small">
        Guest interviews stay on this device and need no account.
      </p>

      <p className="auth-switch">
        New here? <Link to="/register">Create an account</Link>
      </p>
    </AuthShell>
  )
}
