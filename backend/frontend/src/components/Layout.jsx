import { Link, NavLink, Outlet } from 'react-router-dom'
import { site } from '../siteConfig.js'

export default function Layout() {
  const year = new Date().getFullYear()
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
          </nav>
        </div>
      </header>

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
