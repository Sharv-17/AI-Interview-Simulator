"""Authentication service: registration, login, sessions and ownership lookups.

Everything security-relevant about accounts happens here, on top of an AuthStore:
normalization, the password policy, Argon2id hashing, opaque session issuance,
expiry/revocation enforcement, rate limiting and the candidate ownership lookup that
the interview API uses.

Rules this module is responsible for:
* a stored password is always an Argon2id hash;
* a stored session is always a hash of a random token, never the token;
* an unknown email and a wrong password produce the same error, after the same
  amount of Argon2 work;
* a session that is expired, revoked, or whose account is inactive authenticates
  nobody, and the cookie alone is never trusted as identity.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Optional

from app import config
from app.services import credentials
from app.services.auth_errors import (
    AccountInactive,
    AuthenticationRequired,
    EmailAlreadyRegistered,
    InvalidCredentials,
    InvalidRegistrationData,
    RateLimited,
)
from app.services.auth_store import AuthStore, MemoryAuthStore, SessionRecord, UserRecord
from app.services.interview_engine import utcnow
from app.services.passwords import dummy_password_hash, hash_password, verify_password
from app.services.rate_limit import RateLimitPolicy, SlidingWindowRateLimiter
from app.services.session_tokens import hash_session_token, new_session_token

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoginResult:
    user: UserRecord
    token: str
    expires_at: datetime


class AuthService:
    def __init__(
        self,
        store: AuthStore,
        interviews=None,
        clock: Callable[[], datetime] = utcnow,
        session_ttl_seconds: Optional[int] = None,
        login_policy: Optional[RateLimitPolicy] = None,
        login_ip_policy: Optional[RateLimitPolicy] = None,
        register_policy: Optional[RateLimitPolicy] = None,
    ) -> None:
        self._store = store
        self._interviews = interviews
        self._clock = clock
        self._session_ttl = session_ttl_seconds or config.AUTH_SESSION_TTL_SECONDS
        window = config.AUTH_LOGIN_RATE_LIMIT_WINDOW_SECONDS
        self._login_limiter = SlidingWindowRateLimiter(
            login_policy or RateLimitPolicy(config.AUTH_LOGIN_RATE_LIMIT_ATTEMPTS, window)
        )
        self._login_ip_limiter = SlidingWindowRateLimiter(
            login_ip_policy or RateLimitPolicy(config.AUTH_LOGIN_IP_RATE_LIMIT_ATTEMPTS, window)
        )
        self._register_limiter = SlidingWindowRateLimiter(
            register_policy
            or RateLimitPolicy(
                config.AUTH_REGISTER_RATE_LIMIT_ATTEMPTS,
                config.AUTH_REGISTER_RATE_LIMIT_WINDOW_SECONDS,
            )
        )

    @property
    def store(self) -> AuthStore:
        return self._store

    @property
    def backend_name(self) -> str:
        return self._store.backend_name

    # --------------------------------------------------------------- registration

    def register(
        self,
        email: str,
        password: str,
        display_name: Optional[str] = None,
        requester: str = "unknown",
    ) -> UserRecord:
        """Create an account and its candidate. Email verification is NOT implemented.

        `display_name` is written onto the candidate that is created here; it never
        creates or re-points a second candidate.
        """
        limit_key = f"register:{requester}"
        self._raise_if_limited([(self._register_limiter, limit_key)])
        self._register_limiter.record(limit_key)

        normalized = credentials.normalize_email(email)
        problem = credentials.email_error(normalized) or credentials.password_error(password)
        if problem:
            raise InvalidRegistrationData(problem)
        if self._store.get_user_by_email(normalized) is not None:
            raise EmailAlreadyRegistered()

        now = self._clock()
        user_id = str(uuid.uuid4())
        candidate_id = str(uuid.uuid4())
        clean_name = " ".join((display_name or "").split()) or None
        try:
            user = self._store.create_user(
                user_id=user_id,
                email=normalized,
                password_hash=hash_password(password),
                candidate_id=candidate_id,
                created_at=now,
                display_name=clean_name,
            )
        except EmailAlreadyRegistered:
            # Lost a race with a concurrent registration of the same address.
            raise
        except Exception:
            logger.exception("Registration failed while creating the account")
            raise

        # Memory backend: the interview store keeps its own candidate registry, so the
        # new candidate must be visible to it. PostgreSQL already holds the row.
        if self._interviews is not None:
            self._interviews.store.register_candidate(candidate_id, now, clean_name)
        logger.info("Account created (email verification not implemented)")
        return user

    # ---------------------------------------------------------------------- login

    def login(self, email: str, password: str, requester: str = "unknown") -> LoginResult:
        normalized = credentials.normalize_email(email)
        email_key = f"login:{normalized}"
        ip_key = f"login-ip:{requester}"
        self._raise_if_limited(
            [(self._login_limiter, email_key), (self._login_ip_limiter, ip_key)]
        )

        problem = credentials.login_password_error(password)
        user = self._store.get_user_by_email(normalized) if not problem else None
        if user is None:
            # Same Argon2 work as a real verification: no timing oracle for "no such user".
            verify_password(password or "", dummy_password_hash())
            self._record_login_failure(email_key, ip_key)
            raise InvalidCredentials()
        if not verify_password(password, user.password_hash):
            self._record_login_failure(email_key, ip_key)
            raise InvalidCredentials()
        if not user.is_active:
            # Only reachable with the correct password, so this cannot enumerate accounts.
            raise AccountInactive()

        self._login_limiter.clear(email_key)
        token, expires_at = self._issue_session(user)
        return LoginResult(user=user, token=token, expires_at=expires_at)

    def _record_login_failure(self, *keys: str) -> None:
        for limiter, key in ((self._login_limiter, keys[0]), (self._login_ip_limiter, keys[1])):
            limiter.record(key)

    @staticmethod
    def _raise_if_limited(entries) -> None:
        waits = [wait for wait in (limiter.retry_after(key) for limiter, key in entries) if wait]
        if waits:
            raise RateLimited(retry_after=max(waits))

    # ------------------------------------------------------------------- sessions

    def _issue_session(self, user: UserRecord) -> tuple:
        now = self._clock()
        token = new_session_token()
        expires_at = now + timedelta(seconds=self._session_ttl)
        self._store.create_session(
            user_id=user.user_id,
            token_hash=hash_session_token(token),
            created_at=now,
            expires_at=expires_at,
        )
        return token, expires_at

    def authenticate(self, token: Optional[str]) -> Optional[UserRecord]:
        """Resolve a raw session token to an active user, or None.

        Expired and revoked sessions are refused here, server-side; the cookie's own
        Max-Age is only a browser convenience and is never trusted.
        """
        if not token or len(token) < 32:
            return None
        record = self._store.get_session(hash_session_token(token))
        if record is None:
            return None
        now = self._clock()
        if record.revoked_at is not None or record.expires_at <= now:
            return None
        user = self._store.get_user(record.user_id)
        if user is None or not user.is_active:
            # A disabled account must not keep a live session.
            self._store.revoke_session(record.session_id, now)
            return None
        if record.last_used_at is None or (now - record.last_used_at).total_seconds() >= config.AUTH_SESSION_TOUCH_SECONDS:
            self._store.touch_session(record.session_id, now)
        return user

    def logout(self, token: Optional[str]) -> bool:
        """Revoke the session behind this token. Idempotent; no error for a dead token."""
        if not token or len(token) < 32:
            return False
        record = self._store.get_session(hash_session_token(token))
        if record is None:
            return False
        return self._store.revoke_session(record.session_id, self._clock())

    def revoke_all_sessions(self, user_id: str) -> int:
        return self._store.revoke_all_sessions(user_id, self._clock())

    def session_records(self, user_id: str):
        return self._store.sessions_of(user_id)

    # ------------------------------------------------------------------ ownership

    def require_user(self, token: Optional[str]) -> UserRecord:
        user = self.authenticate(token)
        if user is None:
            raise AuthenticationRequired()
        return user

    def owner_of_candidate(self, candidate_id: Optional[str]) -> Optional[str]:
        """The account that owns a candidate, or None when it has no owner (guest)."""
        if not candidate_id:
            return None
        return self._store.owner_of_candidate(candidate_id)

    # ------------------------------------------------------------------ operations

    def reset_rate_limits(self) -> None:
        """Clear all counters (tests, and an operator recovering from a lockout storm)."""
        self._login_limiter.reset()
        self._login_ip_limiter.reset()
        self._register_limiter.reset()


# --- wiring ---------------------------------------------------------------------

_service: Optional[AuthService] = None


def build_auth_service_from_config() -> AuthService:
    from app.services.interview_service import get_interview_service

    interviews = get_interview_service()
    backend = config.STORAGE_BACKEND or ("postgres" if config.DATABASE_URL else "memory")
    if backend == "postgres":
        if not config.DATABASE_URL:
            raise RuntimeError("STORAGE_BACKEND=postgres requires DATABASE_URL.")
        from app.db.postgres_auth_store import PostgresAuthStore

        return AuthService(PostgresAuthStore.from_url(config.DATABASE_URL), interviews)
    if backend == "memory":
        logger.warning(
            "STORAGE_BACKEND=memory: accounts and sessions are NOT persisted. Development/testing only."
        )
        return AuthService(MemoryAuthStore(), interviews)
    raise RuntimeError(f"Unknown STORAGE_BACKEND {backend!r}. Use 'postgres' or 'memory'.")


def get_auth_service() -> AuthService:
    global _service
    if _service is None:
        _service = build_auth_service_from_config()
    return _service


def set_auth_service(service: Optional[AuthService]) -> None:
    """Replace the shared service (tests)."""
    global _service
    _service = service
