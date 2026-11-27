"""Argon2id password hashing.

Uses `argon2-cffi` (the reference binding, audited and maintained) with an explicit
Argon2id configuration rather than the library default so the cost parameters are a
documented decision:

    time_cost=3, memory_cost=64 MiB, parallelism=4, hash_len=32, salt_len=16

Those are the OWASP Password Storage Cheat Sheet's baseline for Argon2id (19 MiB,
t=2 is the floor; 64 MiB is comfortably above it) and cost roughly 80 ms per hash on
a laptop CPU.

Plaintext passwords never reach a log line, an exception message or a response model:
callers pass the plaintext in and get either a hash or a boolean back.
"""

from functools import lru_cache
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type

TIME_COST = 3
MEMORY_COST = 65536  # KiB == 64 MiB
PARALLELISM = 4
HASH_LENGTH = 32
SALT_LENGTH = 16


@lru_cache(maxsize=1)
def _hasher() -> PasswordHasher:
    return PasswordHasher(
        time_cost=TIME_COST,
        memory_cost=MEMORY_COST,
        parallelism=PARALLELISM,
        hash_len=HASH_LENGTH,
        salt_len=SALT_LENGTH,
        type=Type.ID,
    )


def hash_password(password: str) -> str:
    """Hash a password for storage. Raises nothing password-specific on purpose."""
    return _hasher().hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time verification. Never raises for a wrong password or bad hash."""
    try:
        return _hasher().verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True when a stored hash was made with weaker parameters than today's."""
    try:
        return _hasher().check_needs_rehash(password_hash)
    except InvalidHashError:
        return False


_dummy_hash: Optional[str] = None


def dummy_password_hash() -> str:
    """A hash to verify against when the email is unknown.

    Without this, an unknown email returns in microseconds while a known one spends
    ~80 ms in Argon2, which is a reliable account-enumeration signal.
    """
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password("not-a-real-password-placeholder")
    return _dummy_hash
