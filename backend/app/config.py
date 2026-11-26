"""Application-wide configuration.

Centralized so values used by more than one module are never hard-coded in
multiple places. Voice settings can be overridden with environment variables
(see .env.example); invalid values fail fast at startup with a clear message.
"""

import os

# Default per-question time limit, in seconds. Fixed for this MVP; a
# later stage could make this per-question or configurable via
# environment variables without changing any of the timing logic that
# reads it.
DEFAULT_QUESTION_TIME_LIMIT_SECONDS = 90


def _env_str(name: str, default: str = "") -> str:
    return (os.environ.get(name) or "").strip() or default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Environment variable {name} must be true or false, got {raw!r}")


def _env_positive_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"Environment variable {name} must be a number, got {raw!r}") from None
    if value <= 0:
        raise ValueError(f"Environment variable {name} must be positive, got {value}")
    return value


def _env_positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"Environment variable {name} must be an integer, got {raw!r}") from None
    if value <= 0:
        raise ValueError(f"Environment variable {name} must be positive, got {value}")
    return value


# ---- Voice answers (Stage 3.8) ---------------------------------------------

# Largest audio upload accepted by POST /interview/{id}/transcribe.
MAX_AUDIO_UPLOAD_BYTES = _env_positive_int("MAX_AUDIO_UPLOAD_BYTES", 10 * 1024 * 1024)

# Longest accepted recording. The browser is expected to stop recording at this
# limit; the server also rejects audio that decodes to noticeably longer.
MAX_RECORDING_SECONDS = _env_positive_int("MAX_RECORDING_SECONDS", 60)
RECORDING_DURATION_TOLERANCE_SECONDS = 5

# Longest the server waits for transcription before giving up.
TRANSCRIPTION_TIMEOUT_SECONDS = _env_positive_int("TRANSCRIPTION_TIMEOUT_SECONDS", 60)

# faster-whisper model name. "base.en" is small and English-only; larger models
# ("small.en", "medium.en") are more accurate but slower and bigger to download.
WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "").strip() or "base.en"


# ---- Storage (Phase 3) -------------------------------------------------------
# "postgres" needs DATABASE_URL. "memory" keeps everything in the process and is
# lost on restart: development and automated tests only. If STORAGE_BACKEND is
# unset, PostgreSQL is used when DATABASE_URL is set; otherwise startup fails with
# a clear message (see app/services/interview_service.py).
STORAGE_BACKEND = _env_str("STORAGE_BACKEND").lower()
DATABASE_URL = _env_str("DATABASE_URL")

# ---- Answer deadlines (Phase 4) ----------------------------------------------
# A question's time limit is its estimated_time_seconds (DEFAULT_QUESTION_TIME_LIMIT_SECONDS
# if the bank has none). An answer is accepted until limit + this grace period.
ANSWER_GRACE_SECONDS = _env_positive_int("ANSWER_GRACE_SECONDS", 15)

# Longest accepted answer text / source code, in characters.
MAX_ANSWER_CHARS = _env_positive_int("MAX_ANSWER_CHARS", 20000)

# Integrity indicators (never used for scoring).
MAX_INTEGRITY_EVENTS_PER_REQUEST = 50
MAX_INTEGRITY_EVENTS_PER_INTERVIEW = 2000
# Text typed faster than this (characters/second) is flagged as an indicator only.
FAST_SUBMISSION_CHARS_PER_SECOND = _env_positive_float("FAST_SUBMISSION_CHARS_PER_SECOND", 25.0)
FAST_SUBMISSION_MIN_CHARS = 200

# ---- AI answer evaluation (Phase 2) ------------------------------------------
# LLM_PROVIDER: "anthropic" | "openai_compatible". "mock" exists for automated tests
# only and is refused unless ALLOW_MOCK_LLM=true. Keys come from the environment only.
LLM_PROVIDER = _env_str("LLM_PROVIDER").lower()
ALLOW_MOCK_LLM = _env_bool("ALLOW_MOCK_LLM", False)
LLM_TIMEOUT_SECONDS = _env_positive_float("LLM_TIMEOUT_SECONDS", 30.0)
LLM_MAX_ATTEMPTS = _env_positive_int("LLM_MAX_ATTEMPTS", 3)
LLM_RETRY_BASE_SECONDS = _env_positive_float("LLM_RETRY_BASE_SECONDS", 0.5)
LLM_MAX_TOKENS = _env_positive_int("LLM_MAX_TOKENS", 1500)
# How many times a candidate/frontend may re-request evaluation of one answer.
MAX_EVALUATION_RETRIES = _env_positive_int("MAX_EVALUATION_RETRIES", 5)

ANTHROPIC_API_KEY = _env_str("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = _env_str("ANTHROPIC_MODEL", "claude-sonnet-5-5")
ANTHROPIC_BASE_URL = _env_str("ANTHROPIC_BASE_URL", "https://api.anthropic.com")

OPENAI_API_KEY = _env_str("OPENAI_API_KEY")
OPENAI_MODEL = _env_str("OPENAI_MODEL")
OPENAI_BASE_URL = _env_str("OPENAI_BASE_URL", "https://api.openai.com/v1")


# ---- Account authentication (Phase 5) ----------------------------------------
# Sessions are opaque random tokens delivered in an HttpOnly cookie; only a SHA-256
# hash of the token is stored, so a database dump cannot be replayed as a login.
# Expiry is absolute and enforced server-side (no sliding extension of expires_at).
AUTH_SESSION_TTL_SECONDS = _env_positive_int("AUTH_SESSION_TTL_SECONDS", 7 * 24 * 60 * 60)
AUTH_SESSION_COOKIE_NAME = _env_str("AUTH_SESSION_COOKIE_NAME", "ais_session")

# Secure must stay on wherever the site is served over HTTPS. It defaults to on;
# only a plain-HTTP development machine should set AUTH_COOKIE_SECURE=false.
AUTH_COOKIE_SECURE = _env_bool("AUTH_COOKIE_SECURE", True)
AUTH_COOKIE_SAMESITE = _env_str("AUTH_COOKIE_SAMESITE", "lax").lower()
if AUTH_COOKIE_SAMESITE not in {"lax", "strict"}:
    raise ValueError(
        f"Environment variable AUTH_COOKIE_SAMESITE must be 'lax' or 'strict', got {AUTH_COOKIE_SAMESITE!r}"
    )
# Empty means "host-only cookie" (recommended).
AUTH_COOKIE_DOMAIN = _env_str("AUTH_COOKIE_DOMAIN") or None

# last_used_at is only written when it is older than this, so a session is not a
# write on every request.
AUTH_SESSION_TOUCH_SECONDS = _env_positive_int("AUTH_SESSION_TOUCH_SECONDS", 60)

# Failed login attempts allowed per email and per client address, per window.
AUTH_LOGIN_RATE_LIMIT_ATTEMPTS = _env_positive_int("AUTH_LOGIN_RATE_LIMIT_ATTEMPTS", 10)
AUTH_LOGIN_IP_RATE_LIMIT_ATTEMPTS = _env_positive_int("AUTH_LOGIN_IP_RATE_LIMIT_ATTEMPTS", 50)
AUTH_LOGIN_RATE_LIMIT_WINDOW_SECONDS = _env_positive_int("AUTH_LOGIN_RATE_LIMIT_WINDOW_SECONDS", 300)
# Registration attempts allowed per client address, per window.
AUTH_REGISTER_RATE_LIMIT_ATTEMPTS = _env_positive_int("AUTH_REGISTER_RATE_LIMIT_ATTEMPTS", 20)
AUTH_REGISTER_RATE_LIMIT_WINDOW_SECONDS = _env_positive_int("AUTH_REGISTER_RATE_LIMIT_WINDOW_SECONDS", 3600)

# Origins allowed to make cookie-authenticated state-changing requests (CSRF).
# Comma separated, e.g. "https://app.example.com,https://www.example.com".
# When empty, only same-origin requests are accepted (Origin host == request host).
AUTH_ALLOWED_ORIGINS = tuple(
    origin.strip().rstrip("/")
    for origin in _env_str("AUTH_ALLOWED_ORIGINS").split(",")
    if origin.strip()
)

# Set when the application sits behind a reverse proxy that terminates TLS and sets
# X-Forwarded-For; otherwise the socket address is used for rate limiting.
AUTH_TRUST_PROXY = _env_bool("AUTH_TRUST_PROXY", False)
