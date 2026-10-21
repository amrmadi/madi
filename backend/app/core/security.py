"""Password hashing and access-token helpers.

Plain-language explanation
--------------------------
Passwords are NEVER stored as text. Instead we store a *hash* — a one-way
scramble. When someone logs in, we hash what they typed and compare hashes.
You cannot get the password back from a hash, so a stolen database does not
leak passwords.

For this we use `pwdlib` with **Argon2**, the current recommended algorithm
(winner of the Password Hashing Competition). `pwdlib` is the maintained
successor to the older `passlib`, which is unmaintained and breaks on modern
Python versions.

Login state is carried by a **JSON Web Token (JWT)**: a signed string the
client sends with each request. Signed means the server can detect tampering;
it does NOT encrypt the contents, so no secrets are ever put inside the token.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from pwdlib import PasswordHash

from backend.app.core.config import get_settings

# A single, module-level hasher. Argon2 is the default algorithm.
# Creating this once is important: it is relatively expensive to set up.
_password_hash = PasswordHash.recommended()

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


def hash_password(plain_password: str) -> str:
    """Turn a plain password into a safe, storable hash.

    Example: `hash_password("hunter2")` -> `"$argon2id$v=19$m=65536,..."`
    """
    return _password_hash.hash(plain_password)


def verify_password(plain_password: str, stored_hash: str) -> bool:
    """Return True if `plain_password` matches the stored hash.

    Uses a constant-time comparison internally, which prevents timing attacks
    (where an attacker guesses a password by measuring how long a check takes).
    """
    try:
        return _password_hash.verify(plain_password, stored_hash)
    except Exception:
        # A malformed or truncated hash must never crash the login endpoint —
        # it just means "this is not a valid credential".
        return False


# ---------------------------------------------------------------------------
# JSON Web Tokens
# ---------------------------------------------------------------------------
ACCESS_TOKEN_TYPE = "access"


def create_access_token(
    *,
    subject: str,
    role: str,
    expires_minutes: int | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Create a signed access token for a user.

    `subject` is the user id as a string (JWT requires a string `sub`).
    `role` is embedded so authorization checks do not need a database hit.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    lifetime = timedelta(
        minutes=expires_minutes
        if expires_minutes is not None
        else settings.access_token_expire_minutes
    )

    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "type": ACCESS_TOKEN_TYPE,
        "iat": int(now.timestamp()),  # issued at
        "exp": int((now + lifetime).timestamp()),  # expiry
        "jti": uuid.uuid4().hex,  # unique token id
    }
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Verify a token's signature and expiry, and return its claims.

    Raises `jwt.InvalidTokenError` (or a subclass) if the token is expired,
    tampered with, or signed with the wrong key. Callers translate that into a
    401 response — we never trust an unverified token.
    """
    settings = get_settings()
    return jwt.decode(
        token,
        settings.secret_key,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "sub"]},
    )
