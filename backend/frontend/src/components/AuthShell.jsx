// The sign-in and registration pages are laid out like the cover of an exam paper:
// what the paper is, how it works, and the instructions, with the form beside it.
// Every line must stay true to the backend: no invented numbers or sample results.

const DETAILS = [
  ['Questions', '1 to 20, your choice'],
  ['Time allowed', 'Set for each question'],
  ['Marked', 'Out of 10, after every answer'],
]

const INSTRUCTIONS = [
  'Choose a topic, a starting difficulty and how many questions you want.',
  'Answer each question before its time runs out. Type your answer, or speak it and correct the transcript.',
  'Each answer is marked out of 10 with notes on what you covered and what you missed. The next question is chosen from how you did.',
  'Marks are given by an AI model and can be wrong. Treat them as practice feedback, not a verdict.',
]

export default function AuthShell({ children }) {
  return (
    <div className="auth-desk">
      <div className="container">
        <div className="auth-sheet">
          <section className="cover">
            <h1 className="cover-title">Technical interview practice paper</h1>
            <dl className="cover-details">
              {DETAILS.map(([term, value]) => (
                <div key={term}>
                  <dt>{term}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
            <h2 className="cover-heading">Instructions to candidates</h2>
            <ol className="instructions">
              {INSTRUCTIONS.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ol>
          </section>

          <section className="auth-panel">
            <div className="auth-panel-inner">{children}</div>
          </section>
        </div>
      </div>
    </div>
  )
}
