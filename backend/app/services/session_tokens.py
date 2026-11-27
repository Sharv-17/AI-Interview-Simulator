"""Opaque session tokens: generation and hashing.

The token is 32 bytes from `secrets` (256 bits of CSPRNG output), encoded URL-safe so
it can live in a cookie without escaping. Only its SHA-256 hex digest is stored.

A fast hash is the right choice *here* and only here: the token is already
high-entropy random data, so there is nothing to guess and no need for a slow KDF —
lookups must be a single indexed equality. Passwords are different and use Argon2id
(app/services/passwords.py).
"""

import hashlib
import secrets

TOKEN_BYTES = 32
MIN_TOKEN_LENGTH = 32  # anything shorter is not one of ours; reject before hashing


def new_session_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
