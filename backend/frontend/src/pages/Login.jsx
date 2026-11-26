import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Eye, EyeOff } from 'lucide-react'
import AuthShell from '../components/AuthShell.jsx'
import usePageTitle from '../hooks/usePageTitle.js'
import {
  LOGIN_UNAVAILABLE,
  UNAVAILABLE_NOTE,
  accountsAvailable,
  validateEmail,
  validatePassword,
} from '../lib/auth.js'

export default function Login() {
  usePageTitle('Sign in')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState({})
  const [showPassword, setShowPassword] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const emailRef = useRef(null)
  const passwordRef = useRef(null)
  const alertRef = useRef(null)

  // Move focus to the notice so mobile users (who submit from below it) see the
  // result without hunting for it. role="alert" still announces it to screen readers.
  useEffect(() => {
    if (submitted) alertRef.current?.focus()
  }, [submitted])

  function handleSubmit(event) {
    event.preventDefault()
    const nextErrors = { email: validateEmail(email), password: validatePassword(password) }
    setErrors(nextErrors)
    setSubmitted(false)
    if (nextErrors.email) return emailRef.current?.focus()
    if (nextErrors.password) return passwordRef.current?.focus()
    // The backend has no authentication endpoint, so no request is made and no
    // signed-in state is ever claimed. Only the unavailable notice is ever shown.
    if (!accountsAvailable) setSubmitted(true)
  }

  return (
    <AuthShell>
      <h2>Welcome back</h2>
      <p className="auth-sub">
        Continue your preparation with AI-powered technical interviews tailored to your skills and
        progress.
      </p>

      {!accountsAvailable && <p className="auth-availability">{UNAVAILABLE_NOTE}</p>}

      {submitted && (
        <div className="alert alert-warn" role="alert" tabIndex={-1} ref={alertRef}>
          {LOGIN_UNAVAILABLE}
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

        <button type="submit" className="btn btn-primary btn-block">Sign In</button>
      </form>

      <div className="auth-divider">or</div>

      <Link to="/start" className="btn btn-secondary btn-block">Continue as Guest</Link>
      <p className="auth-guest-note muted small">
        Guest interviews stay on this device and need no account.
      </p>

      <p className="auth-switch">
        New here? <Link to="/register">Create an account</Link>
      </p>
    </AuthShell>
  )
}
