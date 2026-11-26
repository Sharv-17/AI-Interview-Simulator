"""FastAPI dependencies for sessions, CSRF and candidate/interview ownership.

The interview API keeps its existing guest contract: a request with no session is a
guest request and is handled exactly as before. A request *with* a valid session is
never allowed to reach an interview that belongs to a different account, and a client
supplied `candidate_id` can never override the owner the database reports.
"""

import logging
from typing import Optional
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request

from app import config
from app.api.errors import coded
from app.services.auth_errors import AuthenticationRequired
from app.services.auth_service import AuthService, get_auth_service
from app.services.auth_store import UserRecord
from app.services.evaluation_errors import InterviewNotFoundError
from app.services.interview_service import InterviewService, get_interview_service

logger = logging.getLogger(__name__)

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
SESSION_COOKIE = config.AUTH_SESSION_COOKIE_NAME


def client_address(request: Request) -> str:
    """Best-effort caller address for rate limiting.

    X-Forwarded-For is only honoured when AUTH_TRUST_PROXY is on and the application
    really is behind a proxy that sets it; otherwise a client could pick its own
    rate-limit bucket by sending the header.
    """
    if config.AUTH_TRUST_PROXY:
        forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        if forwarded:
            return forwarded
    return request.client.host if request.client else "unknown"


def session_token(request: Request) -> Optional[str]:
    return request.cookies.get(SESSION_COOKIE)


def get_optional_current_user(
    request: Request, auth: AuthService = Depends(get_auth_service)
) -> Optional[UserRecord]:
    """The signed-in user, or None. Never raises: guest routes depend on this."""
    return auth.authenticate(session_token(request))


def require_authenticated_user(
    user: Optional[UserRecord] = Depends(get_optional_current_user),
) -> UserRecord:
    if user is None:
        raise AuthenticationRequired()
    return user


# The name used by the account API and by any future route that needs a hard requirement.
get_current_user = require_authenticated_user


def enforce_csrf(request: Request) -> None:
    """Reject cross-site state-changing requests that arrive with a session cookie.

    Two independent checks:
    * `Sec-Fetch-Site` (when the browser sends it) must be same-origin or a direct
      navigation;
    * `Origin` must match the request host, or one of AUTH_ALLOWED_ORIGINS.

    The SameSite=Lax session cookie is the third layer: browsers do not attach it to
    cross-site POSTs at all.
    """
    if request.method in SAFE_METHODS:
        return
    site = (request.headers.get("sec-fetch-site") or "").strip().lower()
    if site and site not in {"same-origin", "none"}:
        raise coded(403, "csrf_rejected", "Cross-site request rejected.")
    origin = (request.headers.get("origin") or "").strip()
    if not origin:
        return
    if config.AUTH_ALLOWED_ORIGINS:
        if origin.rstrip("/") not in config.AUTH_ALLOWED_ORIGINS:
            raise coded(403, "csrf_rejected", "Cross-site request rejected.")
        return
    host = (request.headers.get("host") or "").strip().lower()
    if not host or urlsplit(origin).netloc.lower() != host:
        raise coded(403, "csrf_rejected", "Cross-site request rejected.")


def require_interview_access(
    interview_id: str,
    auth: AuthService = Depends(get_auth_service),
    interviews: InterviewService = Depends(get_interview_service),
    user: Optional[UserRecord] = Depends(get_optional_current_user),
) -> None:
    """Guests keep access by holding the interview id; accounts get a real check.

    * interview belongs to no account  -> unchanged guest behaviour (possession of the
      interview id, as today);
    * interview belongs to an account  -> that account's session is required.
    """
    try:
        candidate_id = interviews.store.read(interview_id).candidate_id
    except InterviewNotFoundError:
        return  # the endpoint produces the existing 404
    owner = auth.owner_of_candidate(candidate_id)
    if owner is None:
        return
    if user is None:
        raise AuthenticationRequired()
    if user.user_id != owner:
        # 404, not 403: never confirm that another account's interview exists.
        raise HTTPException(status_code=404, detail="Interview not found")


def require_candidate_access(
    candidate_id: str,
    auth: AuthService = Depends(get_auth_service),
    user: Optional[UserRecord] = Depends(get_optional_current_user),
) -> None:
    """The candidate-history equivalent of require_interview_access.

    A guest candidate (no owner) keeps its existing public-by-id behaviour; a candidate
    owned by an account can only be read with that account's session.
    """
    owner = auth.owner_of_candidate(candidate_id)
    if owner is None:
        return
    if user is None:
        raise AuthenticationRequired()
    if user.user_id != owner:
        raise HTTPException(status_code=404, detail="Candidate not found")


def require_candidate_usable(
    candidate_id: Optional[str],
    user: Optional[UserRecord],
    auth: AuthService,
) -> None:
    """Refuse a candidate_id that belongs to somebody else's account."""
    owner = auth.owner_of_candidate(candidate_id)
    if owner is None:
        return  # guest candidate, or unknown (the store answers 404 itself)
    if user is None or user.user_id != owner:
        raise HTTPException(status_code=404, detail="Candidate not found")
