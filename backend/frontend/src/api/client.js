// Thin wrapper around the FastAPI backend.
//
// The browser only ever talks to its own origin: /api/* is forwarded to FastAPI by the
// dev server (vite.config.js) and by the reverse proxy in production (vercel.json).
// Sign-in uses an HttpOnly session cookie, so every request is same-origin with
// credentials and no token is ever readable from JavaScript.

const BASE_URL = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message)
    this.status = status
    this.code = code
  }
}

// Pydantic prefixes its validator messages with "Value error, ". Strip it so a field
// error reads like a sentence.
function cleanValidationMessage(message) {
  return String(message || '').replace(/^Value error,\s*/, '')
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
    return new ApiError(status, 'validation_error', `${field}: ${cleanValidationMessage(first.msg)}`)
  }
  return new ApiError(status, null, `Request failed (HTTP ${status}).`)
}

async function request(path, { method = 'GET', json, form } = {}) {
  // same-origin: the session cookie is sent, and it is never exposed to this code.
  const init = { method, credentials: 'same-origin', headers: {} }
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

  // candidate_id is sent only for a signed-in account (its own candidate, from
  // /api/v1/candidates/me). Guests keep starting anonymous interviews.
  startInterview: ({ topic, difficulty, questionCount, candidateId }) =>
    request('/interview/start', {
      method: 'POST',
      json: {
        topic,
        difficulty,
        question_count: questionCount,
        ...(candidateId ? { candidate_id: candidateId } : {}),
      },
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

  // Account endpoints. The /api/v1 prefix is preserved by the proxy (see vercel.json),
  // unlike the interview routes above where the proxy strips a leading /api.
  auth: {
    register: ({ email, password, displayName }) =>
      request('/v1/auth/register', {
        method: 'POST',
        json: {
          email,
          password,
          ...(displayName ? { display_name: displayName } : {}),
        },
      }),
    login: ({ email, password }) =>
      request('/v1/auth/login', { method: 'POST', json: { email, password } }),
    logout: () => request('/v1/auth/logout', { method: 'POST' }),
    me: () => request('/v1/auth/me'),
    candidate: () => request('/v1/candidates/me'),
    interviews: () => request('/v1/interviews/me'),
    // The candidate-history routes keep their guest contract, but a candidate owned by an
    // account answers 401 without that account's session, so this is only ever called
    // with the signed-in account's own candidate id.
    competencyHistory: (candidateId) =>
      request(`/candidates/${encodeURIComponent(candidateId)}/competency-history`),
  },
}
