import { useState } from 'react'
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useSession } from '../lib/session.js'
import { site } from '../siteConfig.js'

export default function Layout() {
  const year = new Date().getFullYear()
  const navigate = useNavigate()
  const { user, signOut } = useSession()
  const [signOutError, setSignOutError] = useState('')

  async function handleSignOut() {
    setSignOutError('')
    const result = await signOut()
    // The server still knows this account, so the session did not end. Say so instead
    // of navigating away as if it had.
    if (result?.user) {
      setSignOutError(
        'Could not sign you out, so you are still signed in. Please try again.',
      )
      return
    }
    navigate('/', { replace: true })
  }
  return (
    <div className="page">
      <a className="skip-link" href="#main">Skip to content</a>
      <header className="site-header">
        <div className="container header-inner">
          <Link to="/" className="brand">
            <img src="/favicon.svg" alt="" width="24" height="24" />
            <span>{site.name}</span>
          </Link>
          <nav aria-label="Main">
            <NavLink to="/start" className="nav-link">Start an interview</NavLink>
            {user ? (
              <>
                <NavLink to="/dashboard" className="nav-link">Dashboard</NavLink>
                <button type="button" className="nav-link nav-button" onClick={handleSignOut}>
                  Sign out
                </button>
              </>
            ) : (
              <>
                <NavLink to="/guest" className="nav-link">Practise as guest</NavLink>
                <NavLink to="/login" className="nav-link">Sign in</NavLink>
              </>
            )}
          </nav>
        </div>
      </header>

      {signOutError && (
        <div className="container">
          <div className="alert alert-error" role="alert">
            {signOutError}
          </div>
        </div>
      )}

      <main id="main" className="site-main">
        <Outlet />
      </main>

      <footer className="site-footer">
        <div className="container footer-inner">
          <p>&copy; {year} {site.operatorName}</p>
          <nav aria-label="Legal" className="footer-links">
            <Link to="/privacy">Privacy policy</Link>
            <Link to="/terms">Terms and conditions</Link>
            <a href={`mailto:${site.contactEmail}`}>Contact</a>
          </nav>
        </div>
      </footer>
    </div>
  )
}
