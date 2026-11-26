"""Account storage: users, login sessions and the user-to-candidate link.

Two implementations with one contract, mirroring the interview store:
* MemoryAuthStore (here): development and automated tests; lost on restart.
* PostgresAuthStore (app/db/postgres_auth_store.py): production.

The account layer owns `users`, `auth_sessions` and the ownership side of
`candidates.user_id`. It never writes interview rows.
"""

import threading
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from app.services.auth_errors import EmailAlreadyRegistered


@dataclass(frozen=True)
class UserRecord:
    """An account as the application sees it (no plaintext password anywhere)."""

    user_id: str
    email: str
    password_hash: str
    is_active: bool
    is_email_verified: bool
    created_at: datetime
    updated_at: datetime
    candidate_id: Optional[str]


@dataclass(frozen=True)
class SessionRecord:
    """A stored session. `token_hash` is a digest; the raw token is not recoverable."""

    session_id: str
    user_id: str
    token_hash: str
    created_at: datetime
    expires_at: datetime
    revoked_at: Optional[datetime]
    last_used_at: Optional[datetime]


class AuthStore(ABC):
    backend_name = "abstract"

    # -------------------------------------------------------------------- accounts

    @abstractmethod
    def create_user(
        self,
        user_id: str,
        email: str,
        password_hash: str,
        candidate_id: str,
        created_at: datetime,
        display_name: Optional[str] = None,
    ) -> UserRecord:
        """Create the account and its candidate in one transaction.

        `display_name` is stored on that new candidate (never a second candidate).
        Raises EmailAlreadyRegistered when the (normalized) email is taken.
        """

    @abstractmethod
    def get_user_by_email(self, email: str) -> Optional[UserRecord]: ...

    @abstractmethod
    def get_user(self, user_id: str) -> Optional[UserRecord]: ...

    @abstractmethod
    def set_active(self, user_id: str, is_active: bool, now: datetime) -> None:
        """Enable/disable an account (an admin tool or a security response)."""

    @abstractmethod
    def owner_of_candidate(self, candidate_id: str) -> Optional[str]:
        """The user id that owns this candidate, or None for a guest candidate."""

    # -------------------------------------------------------------------- sessions

    @abstractmethod
    def create_session(
        self,
        user_id: str,
        token_hash: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> SessionRecord: ...

    @abstractmethod
    def get_session(self, token_hash: str) -> Optional[SessionRecord]: ...

    @abstractmethod
    def touch_session(self, session_id: str, now: datetime) -> None: ...

    @abstractmethod
    def revoke_session(self, session_id: str, now: datetime) -> bool:
        """Mark one session revoked. False when it was already revoked (idempotent)."""

    @abstractmethod
    def revoke_all_sessions(self, user_id: str, now: datetime) -> int:
        """Revoke every live session of an account (account security response)."""

    @abstractmethod
    def sessions_of(self, user_id: str) -> List[SessionRecord]:
        """All sessions of an account, oldest first (diagnostics and tests)."""

    def startup(self) -> None:
        return None

    def check_ready(self) -> None:
        return None


class MemoryAuthStore(AuthStore):
    backend_name = "memory"

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._users: Dict[str, UserRecord] = {}
        self._sessions: Dict[str, SessionRecord] = {}

    # -------------------------------------------------------------------- accounts

    def create_user(
        self,
        user_id: str,
        email: str,
        password_hash: str,
        candidate_id: str,
        created_at: datetime,
        display_name: Optional[str] = None,
    ) -> UserRecord:
        # The memory backend keeps candidates in the interview store; AuthService
        # registers this one there (with the name) right after this call.
        with self._lock:
            if any(user.email == email for user in self._users.values()):
                raise EmailAlreadyRegistered()
            if any(user.candidate_id == candidate_id for user in self._users.values()):
                raise RuntimeError("candidate is already linked to an account")
            record = UserRecord(
                user_id=user_id,
                email=email,
                password_hash=password_hash,
                is_active=True,
                is_email_verified=False,
                created_at=created_at,
                updated_at=created_at,
                candidate_id=candidate_id,
            )
            self._users[user_id] = record
            return record

    def get_user_by_email(self, email: str) -> Optional[UserRecord]:
        with self._lock:
            return next((user for user in self._users.values() if user.email == email), None)

    def get_user(self, user_id: str) -> Optional[UserRecord]:
        with self._lock:
            return self._users.get(user_id)

    def set_active(self, user_id: str, is_active: bool, now: datetime) -> None:
        with self._lock:
            user = self._users.get(user_id)
            if user is None:
                return
            self._users[user_id] = UserRecord(**{**user.__dict__, "is_active": is_active, "updated_at": now})

    def owner_of_candidate(self, candidate_id: str) -> Optional[str]:
        with self._lock:
            return next(
                (user.user_id for user in self._users.values() if user.candidate_id == candidate_id),
                None,
            )

    # -------------------------------------------------------------------- sessions

    def create_session(
        self,
        user_id: str,
        token_hash: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> SessionRecord:
        with self._lock:
            if any(session.token_hash == token_hash for session in self._sessions.values()):
                raise RuntimeError("session token hash collision")
            record = SessionRecord(
                session_id=str(uuid.uuid4()),
                user_id=user_id,
                token_hash=token_hash,
                created_at=created_at,
                expires_at=expires_at,
                revoked_at=None,
                last_used_at=None,
            )
            self._sessions[record.session_id] = record
            return record

    def get_session(self, token_hash: str) -> Optional[SessionRecord]:
        with self._lock:
            return next(
                (session for session in self._sessions.values() if session.token_hash == token_hash),
                None,
            )

    def touch_session(self, session_id: str, now: datetime) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            self._sessions[session_id] = SessionRecord(**{**session.__dict__, "last_used_at": now})

    def revoke_session(self, session_id: str, now: datetime) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or session.revoked_at is not None:
                return False
            self._sessions[session_id] = SessionRecord(**{**session.__dict__, "revoked_at": now})
            return True

    def revoke_all_sessions(self, user_id: str, now: datetime) -> int:
        with self._lock:
            revoked = 0
            for session in list(self._sessions.values()):
                if session.user_id == user_id and session.revoked_at is None:
                    self._sessions[session.session_id] = SessionRecord(
                        **{**session.__dict__, "revoked_at": now}
                    )
                    revoked += 1
            return revoked

    def sessions_of(self, user_id: str) -> List[SessionRecord]:
        with self._lock:
            sessions = [s for s in self._sessions.values() if s.user_id == user_id]
        return sorted(sessions, key=lambda s: (s.created_at, s.session_id))
