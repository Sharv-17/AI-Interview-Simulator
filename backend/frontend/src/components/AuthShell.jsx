import { Link } from 'react-router-dom'
import { Check } from 'lucide-react'
import { site } from '../siteConfig.js'

const POINTS = [
  'Questions adapt after every answer you give',
  'AI feedback on accuracy, depth and clarity',
  'No account needed to start practising',
]

const BANDS = [
  { label: 'HARD', y: 46 },
  { label: 'MEDIUM', y: 101 },
  { label: 'EASY', y: 156 },
]

const STEPS = [
  [26, 158],
  [88, 150],
  [150, 112],
  [212, 104],
  [274, 66],
  [336, 52],
]

// A quiet diagram of the adaptive engine: answers move the interview through the
// difficulty bands. Pure SVG, no images and no animation.
function AdaptiveCurve() {
  return (
    <figure className="auth-visual">
      <svg viewBox="0 0 360 200" role="img" aria-labelledby="auth-visual-title">
        <title id="auth-visual-title">
          Question difficulty rising from easy to hard as answers are scored
        </title>
        {BANDS.map((band) => (
          <g key={band.label} className="auth-band">
            <line x1="16" y1={band.y} x2="344" y2={band.y} />
            <text x="16" y={band.y - 7}>{band.label}</text>
          </g>
        ))}
        <polyline
          className="auth-curve"
          points={STEPS.map(([x, y]) => `${x},${y}`).join(' ')}
        />
        {STEPS.map(([x, y]) => (
          <circle key={`${x}-${y}`} className="auth-dot" cx={x} cy={y} r="4" />
        ))}
      </svg>
      <figcaption>Each answer sets the difficulty of the next question.</figcaption>
    </figure>
  )
}

export default function AuthShell({ children }) {
  return (
    <div className="auth-page">
      <aside className="auth-intro">
        <Link to="/" className="auth-brand">
          <img src="/favicon.svg" alt="" width="28" height="28" />
          <span>{site.name}</span>
        </Link>

        <div className="auth-intro-body">
          <p className="auth-eyebrow">Adaptive technical interviews</p>
          <h1>Prepare smarter. Perform better.</h1>
          <p className="auth-lede">
            Practise with an AI interviewer that scores every answer and picks the next question around
            your strengths and gaps.
          </p>
          <AdaptiveCurve />
          <ul className="auth-points">
            {POINTS.map((point) => (
              <li key={point}>
                <Check size={16} strokeWidth={2.5} aria-hidden="true" />
                <span>{point}</span>
              </li>
            ))}
          </ul>
        </div>
      </aside>

      <section className="auth-panel">
        <div className="auth-panel-inner">{children}</div>
      </section>
    </div>
  )
}
