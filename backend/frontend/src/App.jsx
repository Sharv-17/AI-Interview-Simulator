import { Suspense, lazy } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import Layout from './components/Layout.jsx'
import Dashboard from './pages/Dashboard.jsx'
import Home from './pages/Home.jsx'
import Interview from './pages/Interview.jsx'
import Login from './pages/Login.jsx'
import NotFound from './pages/NotFound.jsx'
import Register from './pages/Register.jsx'
import Privacy from './pages/Privacy.jsx'
import Start from './pages/Start.jsx'
import Terms from './pages/Terms.jsx'
import { useSession } from './lib/session.js'

// The report page carries the charting library, so it loads only when opened.
const Report = lazy(() => import('./pages/Report.jsx'))

function SessionLoading() {
  return (
    <div className="container narrow section">
      <p className="muted">Loading your account</p>
    </div>
  )
}

// "/" is the sign-in page for a guest and the dashboard for an account. It renders
// the form in place (rather than redirecting) so the URL a visitor typed stays put.
function HomeRoute() {
  const { user, loading } = useSession()
  if (loading) return <SessionLoading />
  return user ? <Navigate to="/dashboard" replace /> : <Login />
}

function LoginRoute() {
  const { user, loading } = useSession()
  if (loading) return <SessionLoading />
  return user ? <Navigate to="/dashboard" replace /> : <Login />
}

function RegisterRoute() {
  const { user, loading } = useSession()
  if (loading) return <SessionLoading />
  return user ? <Navigate to="/dashboard" replace /> : <Register />
}

// Only the dashboard is protected. Interview and report links are deliberately not
// guarded: a guest interview must stay openable from a link, and an account report
// answers 401 by itself (the report page explains how to sign in).
function RequireAuth({ children }) {
  const { user, loading } = useSession()
  const location = useLocation()
  if (loading) return <SessionLoading />
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return children
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<HomeRoute />} />
        <Route path="login" element={<LoginRoute />} />
        <Route path="register" element={<RegisterRoute />} />
        <Route path="guest" element={<Home />} />
        <Route
          path="dashboard"
          element={
            <RequireAuth>
              <Dashboard />
            </RequireAuth>
          }
        />
        <Route path="start" element={<Start />} />
        <Route path="interview/:id" element={<Interview />} />
        <Route
          path="report/:id"
          element={
            <Suspense fallback={<div className="container narrow section"><p className="muted">Loading report</p></div>}>
              <Report />
            </Suspense>
          }
        />
        <Route path="privacy" element={<Privacy />} />
        <Route path="terms" element={<Terms />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}
