// Keeps a short list of interview IDs in this browser so people can reopen their reports.
// Nothing else is stored on the device. Storage can be unavailable (private mode, blocked
// storage), so every access is wrapped and failures are ignored.

const KEY = 'ais.recentSessions'
const LIMIT = 10

export function loadRecentSessions() {
  try {
    const raw = window.localStorage.getItem(KEY)
    const list = raw ? JSON.parse(raw) : []
    return Array.isArray(list) ? list : []
  } catch {
    return []
  }
}

export function saveRecentSession(session) {
  try {
    const rest = loadRecentSessions().filter((item) => item.id !== session.id)
    window.localStorage.setItem(KEY, JSON.stringify([session, ...rest].slice(0, LIMIT)))
  } catch {
    // Storage unavailable: the session still works, it just will not be listed.
  }
}

export function clearRecentSessions() {
  try {
    window.localStorage.removeItem(KEY)
  } catch {
    // ignore
  }
}
