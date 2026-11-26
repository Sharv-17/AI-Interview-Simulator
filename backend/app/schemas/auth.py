"""Request/response models for the account API.

Validation is the API boundary: an address is normalized here, and a new password is
checked against the documented policy before any hashing work happens. Response
models never carry a password hash or a session token.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.services import credentials
from app.services.auth_store import UserRecord


class RegisterRequest(BaseModel):
    email: str = Field(..., description="Account email. Stored trimmed and lower-cased.")
    password: str = Field(..., description="At least 12 characters.")
    display_name: Optional[str] = Field(
        default=None,
        max_length=120,
        description="Optional name, stored on the account's new candidate record (not a new candidate).",
    )

    @field_validator("display_name")
    @classmethod
    def _clean_display_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned or None

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        normalized = credentials.normalize_email(value)
        problem = credentials.email_error(normalized)
        if problem:
            raise ValueError(problem)
        return normalized

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        problem = credentials.password_error(value)
        if problem:
            raise ValueError(problem)
        return value


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        # No format error here: an unusable address simply fails authentication, so a
        # malformed address and an unknown one look the same to the caller.
        return credentials.normalize_email(value)

    @field_validator("password")
    @classmethod
    def _bound_password(cls, value: str) -> str:
        problem = credentials.login_password_error(value)
        if problem:
            raise ValueError(problem)
        return value


class UserResponse(BaseModel):
    """Safe account information. Never includes a hash, token or session id."""

    user_id: str
    email: str
    is_active: bool
    is_email_verified: bool
    candidate_id: Optional[str] = Field(
        default=None, description="The candidate record this account owns (stable guest-style id)."
    )
    created_at: datetime

    @classmethod
    def of(cls, user: UserRecord) -> "UserResponse":
        return cls(
            user_id=user.user_id,
            email=user.email,
            is_active=user.is_active,
            is_email_verified=user.is_email_verified,
            candidate_id=user.candidate_id,
            created_at=user.created_at,
        )
