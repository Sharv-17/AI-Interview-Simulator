import { Link } from 'react-router-dom'
import usePageTitle from '../hooks/usePageTitle.js'

export default function NotFound() {
  usePageTitle('Page not found')
  return (
    <div className="container narrow section">
      <h1>Page not found</h1>
      <p>The page you asked for does not exist.</p>
      <p><Link to="/">Go to the home page</Link></p>
    </div>
  )
}
