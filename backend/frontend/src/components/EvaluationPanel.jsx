import { Check, ChevronUp, X } from 'lucide-react'
import { formatScore } from '../lib/format.js'

const CRITERIA = [
  ['technical_score', 'Technical accuracy'],
  ['relevance_score', 'Relevance'],
  ['completeness_score', 'Completeness'],
  ['clarity_score', 'Clarity'],
  ['conceptual_understanding_score', 'Conceptual understanding'],
]

const MARK_ICONS = { tick: Check, missing: ChevronUp, wrong: X }

// `mark` adds a red-pen symbol to each line: a tick, a caret for something left out,
// or a cross for something wrong.
function List({ title, items, mark }) {
  if (!items || items.length === 0) return null
  const Icon = mark ? MARK_ICONS[mark] : null
  return (
    <div className={`eval-list ${Icon ? 'marked' : ''}`}>
      <h4>{title}</h4>
      <ul>
        {items.map((item, i) => (
          <li key={i}>
            {Icon && <Icon size={16} strokeWidth={2.5} aria-hidden="true" />}
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

// A loose hand-drawn ring, like a marker circling the score on a paper.
function MarkRing() {
  return (
    <svg className="mark-ring" viewBox="0 0 120 70" preserveAspectRatio="none" aria-hidden="true">
      <path d="M22 50 C 10 30, 44 6, 82 9 C 114 12, 120 44, 92 58 C 66 70, 20 66, 9 46 C 4 34, 18 22, 36 17" />
    </svg>
  )
}

// Shows one scored answer. `evaluation` is a ConceptualEvaluation or CodingEvaluation.
export default function EvaluationPanel({ evaluation, competencyUpdate }) {
  if (!evaluation) return null
  const hasCriteria = typeof evaluation.technical_score === 'number'
  const max = evaluation.max_score || 10

  return (
    <div className="evaluation">
      <p className="mark" aria-label={`Marked ${formatScore(evaluation.overall_score)} out of ${max}`}>
        <MarkRing />
        <span className="mark-value">{formatScore(evaluation.overall_score)}</span>
        <span className="mark-max">/{max}</span>
      </p>

      {hasCriteria && (
        <dl className="criteria">
          {CRITERIA.map(([key, label]) => (
            <div className="criterion" key={key}>
              <dt>{label}</dt>
              <dd>
                <span className="meter" aria-hidden="true">
                  <span className="meter-fill" style={{ width: `${(evaluation[key] / max) * 100}%` }} />
                </span>
                <span className="criterion-value">{evaluation[key]}/{max}</span>
              </dd>
            </div>
          ))}
        </dl>
      )}

      {typeof evaluation.tests_total === 'number' && (
        <p>
          Tests passed: {evaluation.tests_passed} of {evaluation.tests_total}
          {evaluation.execution_status === 'skipped' && ' (no tests are set up for this question yet)'}
        </p>
      )}

      {evaluation.feedback && <p className="eval-feedback">{evaluation.feedback}</p>}

      <div className="eval-lists">
        <List title="What you did well" items={evaluation.strengths} />
        <List title="What to improve" items={evaluation.weaknesses} />
        <List title="Concepts you covered" items={evaluation.correct_concepts} mark="tick" />
        <List title="Concepts you missed" items={evaluation.missing_concepts} mark="missing" />
        <List title="Incorrect statements" items={evaluation.incorrect_concepts} mark="wrong" />
      </div>

      {competencyUpdate && (
        <p className="muted small">
          Estimated level in {competencyUpdate.competency} moved from{' '}
          {competencyUpdate.previous_theta.toFixed(2)} to {competencyUpdate.new_theta.toFixed(2)} (scale 0 to 1).
        </p>
      )}
      {evaluation.evaluator && <p className="muted small">Scored by: {evaluation.evaluator}</p>}
    </div>
  )
}
