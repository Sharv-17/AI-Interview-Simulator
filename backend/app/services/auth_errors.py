"""Authentication domain errors.

Each error carries the status code, a stable machine-readable `code` and a message
that is safe to return to a client. Nothing here includes a password, a token, a
hash, an email address or a database detail.
"""

from typing import Optional


class AuthError(Exception):
    status_code = 400
    code = "auth_error"
    message = "The request could not be completed."

    def __init__(self, message: Optional[str] = None, retry_after: Optional[int] = None) -> None:
        self.message = message or self.message
        self.retry_after = retry_after
        super().__init__(self.message)

    @property
    def headers(self) -> Optional[dict]:
        if self.retry_after is None:
            return None
        return {"Retry-After": str(self.retry_after)}


class InvalidRegistrationData(AuthError):
    status_code = 422
    code = "invalid_registration_data"


class EmailAlreadyRegistered(AuthError):
    """Registration necessarily reveals that an address is taken.

    This is the accepted trade-off of any sign-up form; the *login* endpoint is where
    enumeration is actually preventable, and there the response is generic.
    """

    status_code = 409
    code = "email_already_registered"
    message = "An account with this email address already exists."


class InvalidCredentials(AuthError):
    """Same response for an unknown email and a wrong password."""

    status_code = 401
    code = "invalid_credentials"
    message = "Incorrect email or password."


class AccountInactive(AuthError):
    status_code = 403
    code = "account_inactive"
    message = "This account is disabled."


class AuthenticationRequired(AuthError):
    status_code = 401
    code = "authentication_required"
    message = "Sign in to continue."


class RateLimited(AuthError):
    status_code = 429
    code = "rate_limited"
    message = "Too many attempts. Try again later."


class AccountResourceMissing(AuthError):
    """The signed-in account has no candidate record (should not happen)."""

    status_code = 404
    code = "candidate_not_found"
    message = "Candidate not found."
