"""Credential normalization and the documented password policy.

One implementation so the API (Pydantic validators) and the service layer agree
exactly on what a valid email and an acceptable password are.

The password policy is deliberately short and documented rather than a long list of
composition rules (NIST SP 800-63B): length is what matters, and arbitrary "must
contain a symbol" rules push users toward predictable substitutions. There is no
server-side password policy beyond this because there are no password-recovery or
password-change flows yet; changing that must start here.
"""

import re
from typing import Optional

MAX_EMAIL_LENGTH = 254
MAX_EMAIL_LOCAL_LENGTH = 64

PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128
MAX_LOGIN_PASSWORD_LENGTH = 1024  # login never reveals the policy; just bound the input

# Deliberately permissive: message transfer agents accept far more shapes than this.
# The address is never the authorization factor; the password is.
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(raw: str) -> str:
    """Trim and lower-case an address; the stored form is the comparison key."""
    return (raw or "").strip().lower()


def email_error(email: str) -> Optional[str]:
    """Return a user-facing problem with a normalized email, or None if usable."""
    if not email:
        return "Enter your email address."
    if len(email) > MAX_EMAIL_LENGTH:
        return f"Email addresses must be at most {MAX_EMAIL_LENGTH} characters."
    local, _, domain = email.partition("@")
    if len(local) > MAX_EMAIL_LOCAL_LENGTH:
        return "That email address is too long."
    if not _EMAIL_PATTERN.match(email):
        return "Enter a valid email address."
    return None


def password_error(password: str) -> Optional[str]:
    """Return a user-facing problem with a new password, or None if acceptable."""
    if not password:
        return "Enter a password."
    if len(password) < PASSWORD_MIN_LENGTH:
        return f"Passwords must be at least {PASSWORD_MIN_LENGTH} characters."
    if len(password) > PASSWORD_MAX_LENGTH:
        return f"Passwords must be at most {PASSWORD_MAX_LENGTH} characters."
    if not password.strip():
        return "Passwords cannot be only spaces."
    return None


def login_password_error(password: str) -> Optional[str]:
    """Only bound the input; an empty or short password is simply a failed attempt.

    Returning 422 for an empty password would make "blank" distinguishable from
    "wrong", so those go through the normal generic 401 path instead.
    """
    if len(password or "") > MAX_LOGIN_PASSWORD_LENGTH:
        return "That password is too long."
    return None
