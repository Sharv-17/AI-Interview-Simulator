import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api/client.js'
import { SessionContext } from '../lib/session.js'

// One place that knows whether somebody is signed in.
//
// On load it asks the backend (the cookie decides, not this code). After a sign-in or
// sign-out it re-answers from the server rather than guessing. A 401 means guest, and a
// network failure is treated as guest too, so the guest experience is never blocked by
// an account outage.
export default function SessionProvider({ children }) {
  const [user, setUser] = useState(null)
  const [candidate, setCandidate] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // Pure: no state writes, so callers decide how to apply the answer.
  const fetchAccount = useCallback(async () => {
    const me = await api.auth.me()
    let ownCandidate = null
    try {
      ownCandidate = await api.auth.candidate()
    } catch (candidateError) {
      // A signed-in account without a candidate should not be possible; keep going.
      if (candidateError?.status !== 404) throw candidateError
    }
    return { me, candidate: ownCandidate }
  }, [])

  const apply = useCallback((account) => {
    setUser(account.me)
    setCandidate(account.candidate)
    setError('')
  }, [])

  const clear = useCallback((message = '') => {
    setUser(null)
    setCandidate(null)
    setError(message)
  }, [])

  const refresh = useCallback(async () => {
    try {
      const account = await fetchAccount()
      apply(account)
      return account.me
    } catch (err) {
      clear(err?.status === 401 ? '' : err?.message || '')
      return null
    } finally {
      setLoading(false)
    }
  }, [fetchAccount, apply, clear])

  useEffect(() => {
    let cancelled = false
    fetchAccount()
      .then((account) => {
        if (!cancelled) apply(account)
      })
      .catch((err) => {
        if (!cancelled) clear(err?.status === 401 ? '' : err?.message || '')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [fetchAccount, apply, clear])

  const signIn = useCallback(
    async ({ email, password }) => {
      await api.auth.login({ email, password })
      const account = await fetchAccount()
      apply(account)
      return account.me
    },
    [fetchAccount, apply],
  )

  // Resolves to the account when the session is still alive, or null when signed out.
  //
  // The cookie is HttpOnly, so only the server can end the session. If the logout call
  // fails (for example a CSRF rejection from a proxy that rewrote the Host header), the
  // session survives: reporting "signed out" here would be undone by the next reload,
  // which is exactly the confusing state this guards against.
  const signOut = useCallback(async () => {
    let failure = null
    try {
      await api.auth.logout()
    } catch (err) {
      failure = err
    }

    let account = null
    try {
      account = await fetchAccount()
    } catch {
      // 401 or unreachable: neither keeps a session alive.
    }

    if (account) {
      apply(account)
      return { user: account.me, error: failure }
    }

    // 401 (or an unreachable server): the cookie is gone or unusable, so drop state.
    clear('')
    return { user: null, error: null }
  }, [fetchAccount, apply, clear])

  const value = useMemo(
    () => ({ user, candidate, loading, error, signIn, signOut, refresh }),
    [user, candidate, loading, error, signIn, signOut, refresh],
  )

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}
