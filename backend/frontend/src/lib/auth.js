// Authentication UI exists, but this backend has NO authentication endpoints yet
// (see backend/app/schemas/candidate.py: "Candidates are lightweight records: there is
// no login in this backend"). The sign-in and registration forms therefore never send
// credentials anywhere and never report a successful sign-in.
//
// When the backend implements the contract in SETUP.md ("Sign-in pages and guest
// access"), set accountsAvailable to true and replace the unavailable notices in
// pages/Login.jsx and pages/Register.jsx with real API calls.

export const accountsAvailable = false

export const UNAVAILABLE_NOTE =
  'Accounts are coming soon. This build has no sign-in API yet, so nothing is sent and guest interviews work exactly as before.'

export const LOGIN_UNAVAILABLE =
  'Sign-in is not available yet, so nothing was sent. Continue as a guest to start an interview.'

export const REGISTER_UNAVAILABLE =
  'Account creation is not available yet, so nothing was sent. Continue as a guest to start an interview.'

// Deliberately minimal: the backend has no password policy, so the form does not
// invent length or character rules that nothing on the server would enforce.
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export function validateName(value) {
  return value.trim() ? '' : 'Enter your full name.'
}

export function validateEmail(value) {
  const email = value.trim()
  if (!email) return 'Enter your email address.'
  if (!EMAIL_PATTERN.test(email)) return 'Enter a valid email address, for example name@example.com.'
  return ''
}

export function validatePassword(value) {
  return value ? '' : 'Enter your password.'
}

export function validatePasswordConfirmation(password, confirmation) {
  if (!confirmation) return 'Re-enter your password.'
  if (password !== confirmation) return 'Passwords do not match.'
  return ''
}
