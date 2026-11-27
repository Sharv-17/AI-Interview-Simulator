"""PostgreSQL account store.

Writes `users`, `auth_sessions` and the owning side of `candidates.user_id` only.
Interview rows, candidate ids and question assignment are untouched: registration
inserts one new candidate row and links it, nothing else.
"""

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import AuthSessionModel, CandidateModel, UserModel
from app.services.auth_errors import EmailAlreadyRegistered
from app.services.auth_store import AuthStore, SessionRecord, UserRecord

logger = logging.getLogger(__name__)


def _normalize_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    return url


class PostgresAuthStore(AuthStore):
    backend_name = "postgres"

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    @classmethod
    def from_url(cls, url: str, **engine_kwargs: Any) -> "PostgresAuthStore":
        options: Dict[str, Any] = {"pool_pre_ping": True, "pool_recycle": 300}
        options.update(engine_kwargs)
        return cls(create_engine(_normalize_url(url), **options))

    def dispose(self) -> None:
        self._engine.dispose()

    def check_ready(self) -> None:
        try:
            with self._engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001 - details stay in the log
            logger.warning("PostgreSQL auth readiness check failed: %s", type(exc).__name__)
            raise RuntimeError("PostgreSQL is not available") from exc

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
        db: Session = self._session_factory()
        try:
            db.add(
                UserModel(
                    id=user_id,
                    email=email,
                    password_hash=password_hash,
                    is_active=True,
                    is_email_verified=False,
                    created_at=created_at,
                    updated_at=created_at,
                )
            )
            # The candidate row references users.id, and these models have no ORM
            # relationship, so the unit of work does not know it must INSERT the user
            # first. Flushing here makes that order explicit; both rows still commit
            # (or roll back) together.
            db.flush()
            # Same transaction as the user: an account always has exactly one candidate.
            db.add(
                CandidateModel(
                    candidate_id=candidate_id,
                    display_name=display_name,
                    external_id=None,
                    user_id=user_id,
                    created_at=created_at,
                )
            )
            db.commit()
            return UserRecord(
                user_id=user_id,
                email=email,
                password_hash=password_hash,
                is_active=True,
                is_email_verified=False,
                created_at=created_at,
                updated_at=created_at,
                candidate_id=candidate_id,
            )
        except IntegrityError:
            db.rollback()
            if self.get_user_by_email(email) is not None:
                raise EmailAlreadyRegistered() from None
            raise
        finally:
            db.close()

    def _user_record(self, db: Session, row: UserModel) -> UserRecord:
        candidate_id = db.execute(
            select(CandidateModel.candidate_id).where(CandidateModel.user_id == row.id)
        ).scalar_one_or_none()
        return UserRecord(
            user_id=row.id,
            email=row.email,
            password_hash=row.password_hash,
            is_active=row.is_active,
            is_email_verified=row.is_email_verified,
            created_at=row.created_at,
            updated_at=row.updated_at,
            candidate_id=candidate_id,
        )

    def get_user_by_email(self, email: str) -> Optional[UserRecord]:
        db: Session = self._session_factory()
        try:
            row = db.execute(select(UserModel).where(UserModel.email == email)).scalar_one_or_none()
            return None if row is None else self._user_record(db, row)
        finally:
            db.close()

    def get_user(self, user_id: str) -> Optional[UserRecord]:
        db: Session = self._session_factory()
        try:
            row = db.get(UserModel, user_id)
            return None if row is None else self._user_record(db, row)
        finally:
            db.close()

    def set_active(self, user_id: str, is_active: bool, now: datetime) -> None:
        db: Session = self._session_factory()
        try:
            db.execute(
                update(UserModel)
                .where(UserModel.id == user_id)
                .values(is_active=is_active, updated_at=now)
            )
            db.commit()
        finally:
            db.close()

    def owner_of_candidate(self, candidate_id: str) -> Optional[str]:
        db: Session = self._session_factory()
        try:
            return db.execute(
                select(CandidateModel.user_id).where(CandidateModel.candidate_id == candidate_id)
            ).scalar_one_or_none()
        finally:
            db.close()

    # -------------------------------------------------------------------- sessions

    def create_session(
        self,
        user_id: str,
        token_hash: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> SessionRecord:
        db: Session = self._session_factory()
        session_id = str(uuid.uuid4())
        try:
            db.add(
                AuthSessionModel(
                    id=session_id,
                    user_id=user_id,
                    token_hash=token_hash,
                    created_at=created_at,
                    expires_at=expires_at,
                    revoked_at=None,
                    last_used_at=None,
                )
            )
            db.commit()
            return SessionRecord(
                session_id=session_id,
                user_id=user_id,
                token_hash=token_hash,
                created_at=created_at,
                expires_at=expires_at,
                revoked_at=None,
                last_used_at=None,
            )
        finally:
            db.close()

    @staticmethod
    def _session_record(row: AuthSessionModel) -> SessionRecord:
        return SessionRecord(
            session_id=row.id,
            user_id=row.user_id,
            token_hash=row.token_hash,
            created_at=row.created_at,
            expires_at=row.expires_at,
            revoked_at=row.revoked_at,
            last_used_at=row.last_used_at,
        )

    def get_session(self, token_hash: str) -> Optional[SessionRecord]:
        db: Session = self._session_factory()
        try:
            row = db.execute(
                select(AuthSessionModel).where(AuthSessionModel.token_hash == token_hash)
            ).scalar_one_or_none()
            return None if row is None else self._session_record(row)
        finally:
            db.close()

    def touch_session(self, session_id: str, now: datetime) -> None:
        db: Session = self._session_factory()
        try:
            db.execute(
                update(AuthSessionModel)
                .where(AuthSessionModel.id == session_id)
                .values(last_used_at=now)
            )
            db.commit()
        finally:
            db.close()

    def revoke_session(self, session_id: str, now: datetime) -> bool:
        db: Session = self._session_factory()
        try:
            result = db.execute(
                update(AuthSessionModel)
                .where(AuthSessionModel.id == session_id, AuthSessionModel.revoked_at.is_(None))
                .values(revoked_at=now)
            )
            db.commit()
            return (result.rowcount or 0) > 0
        finally:
            db.close()

    def revoke_all_sessions(self, user_id: str, now: datetime) -> int:
        db: Session = self._session_factory()
        try:
            result = db.execute(
                update(AuthSessionModel)
                .where(AuthSessionModel.user_id == user_id, AuthSessionModel.revoked_at.is_(None))
                .values(revoked_at=now)
            )
            db.commit()
            return result.rowcount or 0
        finally:
            db.close()

    def sessions_of(self, user_id: str) -> List[SessionRecord]:
        db: Session = self._session_factory()
        try:
            rows = (
                db.execute(
                    select(AuthSessionModel)
                    .where(AuthSessionModel.user_id == user_id)
                    .order_by(AuthSessionModel.created_at, AuthSessionModel.id)
                )
                .scalars()
                .all()
            )
            return [self._session_record(row) for row in rows]
        finally:
            db.close()
