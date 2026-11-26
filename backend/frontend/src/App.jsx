import { Suspense, lazy } from 'react'
import { Route, Routes } from 'react-router-dom'
import Layout from './components/Layout.jsx'
import Home from './pages/Home.jsx'
import Interview from './pages/Interview.jsx'
import Login from './pages/Login.jsx'
import NotFound from './pages/NotFound.jsx'
import Register from './pages/Register.jsx'
import Privacy from './pages/Privacy.jsx'
import Start from './pages/Start.jsx'
import Terms from './pages/Terms.jsx'

// The report page carries the charting library, so it loads only when opened.
const Report = lazy(() => import('./pages/Report.jsx'))

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Home />} />
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
        <Route path="login" element={<Login />} />
        <Route path="register" element={<Register />} />
        <Route path="privacy" element={<Privacy />} />
        <Route path="terms" element={<Terms />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}
