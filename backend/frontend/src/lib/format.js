export const DIFFICULTY_LABELS = { easy: 'Easy', medium: 'Medium', hard: 'Hard' }

export const QUESTION_TYPE_LABELS = {
  conceptual: 'Conceptual',
  coding: 'Coding',
  scenario: 'Scenario',
  system_design: 'System design',
  debugging: 'Debugging',
}

export function formatClock(totalSeconds) {
  const s = Math.max(0, Math.ceil(totalSeconds))
  const minutes = Math.floor(s / 60)
  const seconds = s % 60
  return `${minutes}:${String(seconds).padStart(2, '0')}`
}

export function formatDateTime(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatScore(score) {
  if (score === null || score === undefined) return 'Not scored'
  return Number(score).toFixed(1)
}

export function formatSeconds(seconds) {
  if (seconds === null || seconds === undefined) return ''
  return `${Math.round(seconds)}s`
}

// "tab_switch" -> "Tab switch"
export function humanize(value) {
  if (!value) return ''
  const text = String(value).replace(/_/g, ' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}
