// The signed-in session, as far as the browser can tell.
//
// The backend keeps the session in an HttpOnly cookie, so this module never sees a
// token: it asks GET /api/v1/auth/me and treats a 401 as "guest". Nothing here is
// written to localStorage, and nothing here is an authentication authority; it is a
// cached answer to a server question.

import { createContext, useContext } from 'react'

export const SessionContext = createContext({
  user: null,
  candidate: null,
  loading: true,
  error: '',
  signIn: async () => null,
  signOut: async () => {},
  refresh: async () => null,
})

export function useSession() {
  return useContext(SessionContext)
}
