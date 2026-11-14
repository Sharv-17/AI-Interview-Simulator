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