import { formatScore } from '../lib/format.js'

const CRITERIA = [
  ['technical_score', 'Technical accuracy'],
  ['relevance_score', 'Relevance'],
  ['completeness_score', 'Completeness'],
  ['clarity_score', 'Clarity'],
  ['conceptual_understanding_score', 'Conceptual understanding'],
]

function List({ title, items }) {
  if (!items || items.length === 0) return null
  return (
    <div className="eval-list">
      <h4>{title}</h4>
      <ul>
        {items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    </div>
  )
}

// Shows one scored answer. `evaluation` is a ConceptualEvaluation or CodingEvaluation.
export default function EvaluationPanel({ evaluation, competencyUpdate }) {
  if (!evaluation) return null
  const hasCriteria = typeof evaluation.technical_score === 'number'
  const max = evaluation.max_score || 10

  return (
    <div className="evaluation">
      <div className="eval-score">
        <span className="eval-score-value">{formatScore(evaluation.overall_score)}</span>
        <span className="eval-score-max">out of {max}</span>
      </div>

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
        <List title="Concepts you covered" items={evaluation.correct_concepts} />
        <List title="Concepts you missed" items={evaluation.missing_concepts} />
        <List title="Incorrect statements" items={evaluation.incorrect_concepts} />
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
