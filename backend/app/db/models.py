"""SQLAlchemy models (PostgreSQL). One table per entity.

The interview rules live in the domain (app/services/interview_engine.py); these tables only
store its state. The constraints below are a second line of defence for the rules that
must never be broken even by a bug or a race:

  * one answer per interview question          (candidate_answers.interview_question_id UNIQUE)
  * one evaluation result per answer           (evaluation_results.answer_id UNIQUE)
  * one competency update per answer           (competency_history.answer_id UNIQUE)
  * a question appears once per interview      (interview_questions UNIQUE(interview_id, question_id))
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

TZ = DateTime(timezone=True)


class Base(DeclarativeBase):
    pass


class UserModel(Base):
    """A registered account.

    `password_hash` holds an Argon2id hash (never the password). Sessions live in
    `auth_sessions`, not here, so they can be listed and revoked individually.
    """

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # Stored normalized (trimmed, lower-cased); the unique constraint is the second
    # line of defence against duplicate registrations.
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TZ, nullable=False)


class AuthSessionModel(Base):
    """A server-managed login session.

    Only the SHA-256 hash of the opaque token is stored: the raw token exists solely
    in the client's HttpOnly cookie. Revocation is a timestamp, never a row delete, so
    a replayed cookie can be told apart from an unknown one.
    """

    __tablename__ = "auth_sessions"
    __table_args__ = (
        Index("ix_auth_sessions_user_created", "user_id", "created_at"),
        Index("ix_auth_sessions_expires", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(TZ)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(TZ)


class CandidateModel(Base):
    __tablename__ = "candidates"

    candidate_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(120))
    external_id: Mapped[Optional[str]] = mapped_column(String(120), unique=True)
    # The account that owns this candidate, or NULL for a guest candidate.
    # UNIQUE (NULLs are not compared in PostgreSQL) makes "one account, one candidate"
    # a database guarantee. ON DELETE SET NULL keeps interview history if an account
    # is removed: the candidate and its interviews become guest records again.
    user_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(TZ)


class QuestionModel(Base):
    """Copy of the question bank (the JSON file stays the source of truth; this is synced at startup)."""

    __tablename__ = "questions"

    question_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    question_text: Mapped[str] = mapped_column(Text)
    topic: Mapped[str] = mapped_column(String(120), index=True)
    subtopic: Mapped[Optional[str]] = mapped_column(String(160))
    difficulty: Mapped[str] = mapped_column(String(16))
    question_type: Mapped[str] = mapped_column(String(32))
    competency: Mapped[str] = mapped_column(String(160))
    estimated_time_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    review_status: Mapped[Optional[str]] = mapped_column(String(40))
    source: Mapped[Optional[str]] = mapped_column(String(64))
    tags: Mapped[List[str]] = mapped_column(JSONB)
    expected_concepts: Mapped[List[str]] = mapped_column(JSONB)
    evaluation_criteria: Mapped[List[str]] = mapped_column(JSONB)
    reference_answer: Mapped[Optional[str]] = mapped_column(Text)
    synced_at: Mapped[datetime] = mapped_column(TZ)


class InterviewSessionModel(Base):
    __tablename__ = "interview_sessions"
    __table_args__ = (
        CheckConstraint("status in ('active','completed')", name="ck_interview_status"),
        CheckConstraint("question_count >= 1", name="ck_interview_question_count"),
        Index("ix_interview_sessions_candidate_created", "candidate_id", "created_at"),
        Index("ix_interview_sessions_status", "status"),
    )

    interview_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # Nullable: an interview may be anonymous (no candidate record is ever faked).
    candidate_id: Mapped[Optional[str]] = mapped_column(ForeignKey("candidates.candidate_id", ondelete="RESTRICT"))
    topic: Mapped[str] = mapped_column(String(120))
    difficulty: Mapped[str] = mapped_column(String(16))
    question_count: Mapped[int] = mapped_column(Integer)
    current_question: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    current_question_id: Mapped[Optional[str]] = mapped_column(ForeignKey("questions.question_id"))
    question_started_at: Mapped[Optional[datetime]] = mapped_column(TZ)
    question_time_limit_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    question_grace_seconds: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(TZ)
    completed_at: Mapped[Optional[datetime]] = mapped_column(TZ)


class InterviewQuestionModel(Base):
    """A question assigned to an interview, in order, with its own timing."""

    __tablename__ = "interview_questions"
    __table_args__ = (
        UniqueConstraint("interview_id", "sequence", name="uq_interview_question_sequence"),
        UniqueConstraint("interview_id", "question_id", name="uq_interview_question_once"),
        CheckConstraint("state in ('active','answered','timed_out')", name="ck_interview_question_state"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    interview_id: Mapped[str] = mapped_column(ForeignKey("interview_sessions.interview_id", ondelete="CASCADE"))
    sequence: Mapped[int] = mapped_column(Integer)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.question_id"))
    state: Mapped[str] = mapped_column(String(16))
    assigned_at: Mapped[datetime] = mapped_column(TZ)
    closed_at: Mapped[Optional[datetime]] = mapped_column(TZ)
    time_limit_seconds: Mapped[int] = mapped_column(Integer)
    grace_seconds: Mapped[int] = mapped_column(Integer)


class CandidateAnswerModel(Base):
    __tablename__ = "candidate_answers"
    __table_args__ = (
        CheckConstraint("evaluation_status in ('pending','completed','failed')", name="ck_answer_evaluation_status"),
        Index("ix_candidate_answers_interview", "interview_id"),
    )

    answer_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    interview_question_id: Mapped[int] = mapped_column(
        ForeignKey("interview_questions.id", ondelete="CASCADE"), unique=True
    )
    interview_id: Mapped[str] = mapped_column(ForeignKey("interview_sessions.interview_id", ondelete="CASCADE"))
    question_id: Mapped[str] = mapped_column(String(64))
    answer_text: Mapped[str] = mapped_column(Text)
    answer_source: Mapped[str] = mapped_column(String(16))
    submission_reason: Mapped[str] = mapped_column(String(32))
    language: Mapped[Optional[str]] = mapped_column(String(32))
    submitted_at: Mapped[datetime] = mapped_column(TZ)
    elapsed_seconds: Mapped[float] = mapped_column(Float)
    time_limit_seconds: Mapped[int] = mapped_column(Integer)
    grace_seconds: Mapped[int] = mapped_column(Integer)
    timed_out: Mapped[bool] = mapped_column(Boolean)
    evaluation_status: Mapped[str] = mapped_column(String(16))
    evaluation_error: Mapped[Optional[str]] = mapped_column(String(80))
    evaluation_attempts: Mapped[int] = mapped_column(Integer, default=0)


class EvaluationResultModel(Base):
    __tablename__ = "evaluation_results"
    __table_args__ = (CheckConstraint("overall_score >= 0 and overall_score <= 10", name="ck_evaluation_score_range"),)

    evaluation_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    answer_id: Mapped[str] = mapped_column(ForeignKey("candidate_answers.answer_id", ondelete="CASCADE"), unique=True)
    kind: Mapped[str] = mapped_column(String(16))
    evaluator: Mapped[Optional[str]] = mapped_column(String(120))
    overall_score: Mapped[float] = mapped_column(Float)
    max_score: Mapped[float] = mapped_column(Float)
    details: Mapped[Dict[str, Any]] = mapped_column(JSONB)
    reasoning_summary: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZ)


class CompetencyHistoryModel(Base):
    __tablename__ = "competency_history"
    __table_args__ = (
        CheckConstraint("previous_theta >= 0 and previous_theta <= 1", name="ck_competency_previous_theta"),
        CheckConstraint("new_theta >= 0 and new_theta <= 1", name="ck_competency_new_theta"),
        Index("ix_competency_history_interview_competency", "interview_id", "competency_id", "id"),
        Index("ix_competency_history_candidate_recorded", "candidate_id", "recorded_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    interview_id: Mapped[str] = mapped_column(ForeignKey("interview_sessions.interview_id", ondelete="CASCADE"))
    # Nullable for the same reason as interview_sessions.candidate_id.
    candidate_id: Mapped[Optional[str]] = mapped_column(ForeignKey("candidates.candidate_id", ondelete="RESTRICT"))
    competency_id: Mapped[str] = mapped_column(String(160))
    answer_id: Mapped[str] = mapped_column(ForeignKey("candidate_answers.answer_id", ondelete="CASCADE"), unique=True)
    question_id: Mapped[str] = mapped_column(String(64))
    previous_theta: Mapped[float] = mapped_column(Float)
    new_theta: Mapped[float] = mapped_column(Float)
    normalized_score: Mapped[float] = mapped_column(Float)
    last_score: Mapped[float] = mapped_column(Float)
    questions_attempted: Mapped[int] = mapped_column(Integer)
    recorded_at: Mapped[datetime] = mapped_column(TZ)


class IntegrityEventModel(Base):
    __tablename__ = "integrity_events"
    __table_args__ = (Index("ix_integrity_events_interview_received", "interview_id", "received_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    interview_id: Mapped[str] = mapped_column(ForeignKey("interview_sessions.interview_id", ondelete="CASCADE"))
    question_id: Mapped[Optional[str]] = mapped_column(String(64))
    answer_id: Mapped[Optional[str]] = mapped_column(ForeignKey("candidate_answers.answer_id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(10))
    client_occurred_at: Mapped[Optional[datetime]] = mapped_column(TZ)
    client_source: Mapped[Optional[str]] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(TZ)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    detail: Mapped[Dict[str, Any]] = mapped_column(JSONB)
