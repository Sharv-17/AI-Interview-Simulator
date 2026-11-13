"""Application-wide configuration constants.

Centralized so values used by more than one module — like the default
question time limit — are never hard-coded in multiple places.
"""

# Default per-question time limit, in seconds. Fixed for this MVP; a
# later stage could make this per-question or configurable via
# environment variables without changing any of the timing logic that
# reads it.
DEFAULT_QUESTION_TIME_LIMIT_SECONDS = 90