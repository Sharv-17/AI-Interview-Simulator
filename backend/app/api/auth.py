"""Account endpoints: register, login, logout, current user.

Cookie contract (see docs/AUTHENTICATION.md):
    name    = AUTH_SESSION_COOKIE_NAME (default `ais_session`)
    value   = opaque 256-bit random token
    HttpOnly, Secure (unless AUTH_COOKIE_SECURE=false), SameSite=Lax, Path=/
    Max-Age = AUTH_SESSION_TTL_SECONDS

The raw token is never in a JSON body, and the database stores only its SHA-256 hash.
Email verification and password recovery are NOT implemented: no endpoint here claims
to send mail, and `is_email_verified` stays false.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Request, Response

from app import config
from app.api.auth_deps import (
    client_address,
    enforce_csrf,
    require_authenticated_user,
    session_token,
)
from app.api.errors import http_error_for
from app.schemas.auth import LoginRequest, RegisterRequest, UserResponse
from app.services.auth_errors import AuthError
from app.services.auth_service import AuthService, get_auth_service
from app.services.auth_store import UserRecord
from app.services.interview_engine import utcnow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _run(operation):
    try:
        return operation()
    except AuthError as exc:
        raise http_error_for(exc) from None


def set_session_cookie(response: Response, token: str, expires_at) -> None:
    remaining = max(0, int((expires_at - utcnow()).total_seconds()))
    response.set_cookie(
        key=config.AUTH_SESSION_COOKIE_NAME,
        value=token,
        max_age=remaining,
        expires=expires_at,
        path="/",
        domain=config.AUTH_COOKIE_DOMAIN,
        secure=config.AUTH_COOKIE_SECURE,
        httponly=True,
        samesite=config.AUTH_COOKIE_SAMESITE,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=config.AUTH_SESSION_COOKIE_NAME,
        path="/",
        domain=config.AUTH_COOKIE_DOMAIN,
        secure=config.AUTH_COOKIE_SECURE,
        httponly=True,
        samesite=config.AUTH_COOKIE_SAMESITE,
    )


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=201,
    summary="Create an account",
    responses={
        409: {"description": "The email address is already registered."},
        422: {"description": "Invalid email or password (policy in docs/AUTHENTICATION.md)."},
        429: {"description": "Too many registration attempts from this address."},
    },
)
def register(
    payload: RegisterRequest,
    request: Request,
    auth: AuthService = Depends(get_auth_service),
) -> UserResponse:
    """Create a user and its candidate record.

    Does NOT sign the caller in (call /login for that) and does NOT verify the email
    address: `is_email_verified` is returned as false until a real verification flow
    exists.
    """
    user = _run(
        lambda: auth.register(
            payload.email,
            payload.password,
            display_name=payload.display_name,
            requester=client_address(request),
        )
    )
    return UserResponse.of(user)


@router.post(
    "/login",
    response_model=UserResponse,
    summary="Sign in",
    responses={
        401: {"description": "Incorrect email or password (deliberately identical for both)."},
        403: {"description": "The account is disabled."},
        429: {"description": "Too many failed attempts."},
    },
)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    auth: AuthService = Depends(get_auth_service),
) -> UserResponse:
    """Verify credentials and open a server-side session in an HttpOnly cookie."""
    result = _run(lambda: auth.login(payload.email, payload.password, client_address(request)))
    set_session_cookie(response, result.token, result.expires_at)
    return UserResponse.of(result.user)


@router.post(
    "/logout",
    status_code=204,
    summary="Sign out",
    responses={403: {"description": "Rejected by the cross-site request check."}},
)
def logout(
    request: Request,
    response: Response,
    auth: AuthService = Depends(get_auth_service),
    _csrf: None = Depends(enforce_csrf),
) -> Response:
    """Revoke the current session server-side and clear the cookie.

    Idempotent: signing out without a session (or twice) is still 204.
    """
    token: Optional[str] = session_token(request)
    if token:
        auth.logout(token)
    clear_session_cookie(response)
    response.status_code = 204
    return response


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Current account",
    responses={401: {"description": "No valid session."}},
)
def me(user: UserRecord = Depends(require_authenticated_user)) -> UserResponse:
    """The signed-in account. 401 when the session is missing, expired or revoked."""
    return UserResponse.of(user)
