"""Test configuration.

The default test run must never touch a real database or a real LLM, whatever
the developer's shell has set. These values are applied BEFORE the application
modules are imported (pytest loads this file first).

PostgreSQL-backed tests are opt-in: set TEST_DATABASE_URL (a database that may be
wiped) and they run against it; otherwise they are skipped with a clear reason.
"""

import os

os.environ["STORAGE_BACKEND"] = "memory"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["ALLOW_MOCK_LLM"] = "true"
# The test client speaks plain HTTP; a Secure cookie would not be sent back. The
# Secure attribute itself is asserted separately (tests/test_auth.py).
os.environ["AUTH_COOKIE_SECURE"] = "false"
os.environ.pop("DATABASE_URL", None)
for _key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
    os.environ.pop(_key, None)
