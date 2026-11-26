// Thin wrapper around the FastAPI backend.
// In development, Vite forwards /api/* to http://localhost:8000 (see vite.config.js).
// In production, set VITE_API_BASE_URL to the backend's public URL.

const BASE_URL = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message)
    this.status = status
    this.code = code
  }
}

// The backend returns errors in three shapes:
//   {"detail": "plain text"}
//   {"detail": {"code": "...", "message": "..."}}
//   {"detail": [ ...validation errors... ]}   (HTTP 422)
function toApiError(status, body) {
  const detail = body && body.detail
  if (typeof detail === 'string') return new ApiError(status, null, detail)
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    return new ApiError(status, detail.code || null, detail.message || 'Request failed.')
  }
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0]
    const field = Array.isArray(first.loc) ? first.loc[first.loc.length - 1] : 'input'
    return new ApiError(status, 'validation_error', `${field}: ${first.msg}`)
  }
  return new ApiError(status, null, `Request failed (HTTP ${status}).`)
}

async function request(path, { method = 'GET', json, form } = {}) {
  const init = { method, headers: {} }
  if (json !== undefined) {
    init.headers['Content-Type'] = 'application/json'
    init.body = JSON.stringify(json)
  } else if (form) {
    init.body = form
  }

  let response
  try {
    response = await fetch(`${BASE_URL}${path}`, init)
  } catch {
    throw new ApiError(0, 'network_error', 'Cannot reach the server. Check that the backend is running.')
  }

  let body = null
  const text = await response.text()
  if (text) {
    try {
      body = JSON.parse(text)
    } catch {
      body = null
    }
  }

  if (!response.ok) throw toApiError(response.status, body)
  return body
}

// Retry once when the backend reports that another request for this interview is running.
async function withBusyRetry(fn) {
  try {
    return await fn()
  } catch (err) {
    if (err instanceof ApiError && err.code === 'interview_busy') {
      await new Promise((resolve) => setTimeout(resolve, 1000))
      return fn()
    }
    throw err
  }
}

export const api = {
  listQuestions: () => request('/questions'),
  getQuestion: (questionId) => request(`/questions/${encodeURIComponent(questionId)}`),

  startInterview: ({ topic, difficulty, questionCount }) =>
    request('/interview/start', {
      method: 'POST',
      json: { topic, difficulty, question_count: questionCount },
    }),

  getInterview: (id) => request(`/interview/${encodeURIComponent(id)}`),

  submitAnswer: (id, payload) =>
    withBusyRetry(() =>
      request(`/interview/${encodeURIComponent(id)}/answer`, { method: 'POST', json: payload }),
    ),

  retryEvaluation: (id, questionId) =>
    withBusyRetry(() =>
      request(`/interview/${encodeURIComponent(id)}/answer/retry-evaluation`, {
        method: 'POST',
        json: { question_id: questionId },
      }),
    ),

  advance: (id) =>
    withBusyRetry(() => request(`/interview/${encodeURIComponent(id)}/next`, { method: 'POST' })),

  transcribe: (id, questionId, blob, filename) => {
    const form = new FormData()
    form.append('question_id', questionId)
    form.append('audio', blob, filename)
    return request(`/interview/${encodeURIComponent(id)}/transcribe`, { method: 'POST', form })
  },

  reportIntegrityEvents: (id, questionId, events) =>
    request(`/interview/${encodeURIComponent(id)}/integrity-events`, {
      method: 'POST',
      json: { question_id: questionId, events },
    }),

  getReport: (id) => request(`/interview/${encodeURIComponent(id)}/report`),
}
