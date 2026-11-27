import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Eye, EyeOff } from 'lucide-react'
import AuthShell from '../components/AuthShell.jsx'
import { api } from '../api/client.js'
import usePageTitle from '../hooks/usePageTitle.js'
import {
  MIN_PASSWORD_LENGTH,
  authErrorMessage,
  validateEmail,
  validateName,
  validatePassword,
  validatePasswordConfirmation,
} from '../lib/auth.js'
import { useSession } from '../lib/session.js'

export default function Register() {
  usePageTitle('Create your account')
  const navigate = useNavigate()
  const { signIn } = useSession()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [errors, setErrors] = useState({})
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const nameRef = useRef(null)
  const emailRef = useRef(null)
  const passwordRef = useRef(null)
  const confirmationRef = useRef(null)
  const alertRef = useRef(null)

  // Move focus to the notice so mobile users (who submit from below it) see the
  // result without hunting for it. role="alert" still announces it to screen readers.
  useEffect(() => {
    if (error) alertRef.current?.focus()
  }, [error])

  async function handleSubmit(event) {
    event.preventDefault()
    const nextErrors = {
      name: validateName(name),
      email: validateEmail(email),
      password: validatePassword(password),
      confirmation: validatePasswordConfirmation(password, confirmation),
    }
    setErrors(nextErrors)
    setError('')
    if (nextErrors.name) return nameRef.current?.focus()
    if (nextErrors.email) return emailRef.current?.focus()
    if (nextErrors.password) return passwordRef.current?.focus()
    if (nextErrors.confirmation) return confirmationRef.current?.focus()

    setBusy(true)
    try {
      // The name becomes the display name of the candidate record the account owns.
      await api.auth.register({
        email: email.trim(),
        password,
        displayName: name.trim(),
      })
      // Registration does not open a session, so sign in with the same credentials.
      await signIn({ email: email.trim(), password })
      navigate('/dashboard', { replace: true })
    } catch (err) {
      setError(authErrorMessage(err))
      setBusy(false)
    }
  }

  return (
    <AuthShell>
      <h2>Create your account</h2>
      <p className="auth-sub">
        Keep your interview history and progress together, and pick up where you left off.
      </p>

      {error && (
        <div className="alert alert-error" role="alert" tabIndex={-1} ref={alertRef}>
          {error}
          {error.includes('already exists') && (
            <> <Link to="/login">Sign in</Link>.</>
          )}
        </div>
      )}

      <form className="auth-form" onSubmit={handleSubmit} noValidate>
        <div className="field">
          <label htmlFor="name">Full name</label>
          <input
            ref={nameRef}
            id="name"
            name="name"
            type="text"
            autoComplete="name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            aria-invalid={Boolean(errors.name)}
            aria-describedby={errors.name ? 'name-error' : undefined}
          />
          {errors.name && <p className="field-error" id="name-error">{errors.name}</p>}
        </div>

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
              autoComplete="new-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              aria-invalid={Boolean(errors.password)}
              aria-describedby={
                errors.password ? 'password-error' : 'password-help'
              }
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
          {errors.password ? (
            <p className="field-error" id="password-error">{errors.password}</p>
          ) : (
            <p className="field-help" id="password-help">
              At least {MIN_PASSWORD_LENGTH} characters.
            </p>
          )}
        </div>

        <div className="field">
          <label htmlFor="confirmation">Confirm password</label>
          <input
            ref={confirmationRef}
            id="confirmation"
            name="confirmation"
            type={showPassword ? 'text' : 'password'}
            autoComplete="new-password"
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
            aria-invalid={Boolean(errors.confirmation)}
            aria-describedby={errors.confirmation ? 'confirmation-error' : undefined}
          />
          {errors.confirmation && (
            <p className="field-error" id="confirmation-error">{errors.confirmation}</p>
          )}
        </div>

        <button type="submit" className="btn btn-primary btn-block" disabled={busy}>
          {busy ? 'Creating your account' : 'Create account'}
        </button>

        <p className="auth-terms">
          By creating an account you agree to our <Link to="/terms">Terms and conditions</Link> and{' '}
          <Link to="/privacy">Privacy policy</Link>.
        </p>
      </form>

      <div className="auth-divider">or</div>

      <Link to="/guest" className="btn btn-secondary btn-block">Continue as Guest</Link>
      <p className="auth-guest-note muted small">
        Guest interviews stay on this device and need no account.
      </p>

      <p className="auth-switch">
        Already have an account? <Link to="/login">Sign in</Link>
      </p>
    </AuthShell>
  )
}
