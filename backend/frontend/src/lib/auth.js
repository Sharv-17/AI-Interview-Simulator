// Validation and error copy for the sign-in and registration forms.
//
// These rules mirror the backend (app/services/credentials.py): a valid email shape and
// a password of 12 to 128 characters. The server is still the authority; these checks
// only save a round trip and put the message next to the field.

export const MIN_PASSWORD_LENGTH = 12
export const MAX_PASSWORD_LENGTH = 128

const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/

export function validateName(value) {
  return value.trim() ? '' : 'Enter your full name.'
}

export function validateEmail(value) {
  const email = value.trim()
  if (!email) return 'Enter your email address.'
  if (email.length > 254) return 'That email address is too long.'
  if (!EMAIL_PATTERN.test(email)) return 'Enter a valid email address, for example name@example.com.'
  return ''
}

export function validatePassword(value) {
  if (!value) return 'Enter a password.'
  if (value.length < MIN_PASSWORD_LENGTH) {
    return `Passwords must be at least ${MIN_PASSWORD_LENGTH} characters.`
  }
  if (value.length > MAX_PASSWORD_LENGTH) {
    return `Passwords must be at most ${MAX_PASSWORD_LENGTH} characters.`
  }
  return ''
}

// Sign-in is checked more loosely: an existing account may predate a policy change, and
// the server only answers with a generic failure.
export function validateLoginPassword(value) {
  return value ? '' : 'Enter your password.'
}

export function validatePasswordConfirmation(password, confirmation) {
  if (!confirmation) return 'Re-enter your password.'
  if (password !== confirmation) return 'Passwords do not match.'
  return ''
}

// Turn an ApiError from api/auth calls into a sentence a person can act on.
export function authErrorMessage(err) {
  if (!err) return 'Something went wrong. Try again.'
  switch (err.code) {
    case 'invalid_credentials':
      return 'Incorrect email or password.'
    case 'account_inactive':
      return 'This account is disabled. Contact the operator if you think that is wrong.'
    case 'rate_limited':
      return 'Too many attempts. Wait a few minutes and try again.'
    case 'email_already_registered':
      return 'An account with this email already exists. Sign in instead.'
    case 'authentication_required':
      return 'Sign in to continue.'
    case 'network_error':
      return err.message
    case 'validation_error':
      return err.message
    default:
      return err.message || 'Something went wrong. Try again.'
  }
}
