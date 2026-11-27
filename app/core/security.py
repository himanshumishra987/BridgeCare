"""Password hashing and token primitives.

Design notes
------------
* Passwords are hashed with ``scrypt`` (stdlib ``hashlib``) using a random
  16-byte salt and a versioned, self-describing string format, so parameters
  can be rotated later without breaking existing hashes.
* Access and refresh tokens are signed JWTs (HS256) with an explicit ``typ``
  claim, an issuer/audience pair and a unique ``jti``. The ``typ`` claim is
  verified on decode, so a refresh token can never be replayed as an access
  token (and vice versa).
* Share links use 256-bit opaque random tokens; only a SHA-256 digest of the
  token is stored, so a database leak does not disclose usable links.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 64
SCRYPT_MAXMEM = 64 * 1024 * 1024
_SCRYPT_PREFIX = "scrypt"

TOKEN_ISSUER = "bridgecare-api"
TOKEN_AUDIENCE = "bridgecare-client"
ALGORITHM = "HS256"

ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


class TokenError(Exception):
    """Raised when a token is missing, malformed, expired or of the wrong type."""


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_password(password: str) -> str:
    """Hash a plaintext password with scrypt and a fresh random salt."""
    if not password:
        raise ValueError("password must not be empty")
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
        maxmem=SCRYPT_MAXMEM,
    )
    return "$".join(
        [
            _SCRYPT_PREFIX,
            str(SCRYPT_N),
            str(SCRYPT_R),
            str(SCRYPT_P),
            _b64encode(salt),
            _b64encode(derived),
        ]
    )


def verify_password(password: str, stored_hash: str) -> bool:
    """Constant-time verification of a password against a stored hash."""
    if not password or not stored_hash:
        return False
    try:
        scheme, n_raw, r_raw, p_raw, salt_b64, hash_b64 = stored_hash.split("$")
        if scheme != _SCRYPT_PREFIX:
            return False
        salt = _b64decode(salt_b64)
        expected = _b64decode(hash_b64)
        candidate = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n_raw),
            r=int(r_raw),
            p=int(p_raw),
            dklen=len(expected),
            maxmem=SCRYPT_MAXMEM,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, expected)


# ---------------------------------------------------------------------------
# JWT access / refresh tokens
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IssuedToken:
    token: str
    jti: str
    expires_at: datetime


def _now() -> datetime:
    return datetime.now(UTC)


def _create_token(
    *,
    subject: str,
    role: str,
    token_type: str,
    secret_key: str,
    ttl: timedelta,
    jti: str | None = None,
) -> IssuedToken:
    issued_at = _now()
    expires_at = issued_at + ttl
    token_id = jti or uuid.uuid4().hex
    payload = {
        "sub": subject,
        "role": role,
        "typ": token_type,
        "jti": token_id,
        "iss": TOKEN_ISSUER,
        "aud": TOKEN_AUDIENCE,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, secret_key, algorithm=ALGORITHM)
    return IssuedToken(token=token, jti=token_id, expires_at=expires_at)


def create_access_token(
    *, user_id: uuid.UUID, role: str, secret_key: str, ttl: timedelta
) -> IssuedToken:
    return _create_token(
        subject=str(user_id),
        role=role,
        token_type=ACCESS_TOKEN_TYPE,
        secret_key=secret_key,
        ttl=ttl,
    )


def create_refresh_token(
    *, user_id: uuid.UUID, role: str, secret_key: str, ttl: timedelta
) -> IssuedToken:
    return _create_token(
        subject=str(user_id),
        role=role,
        token_type=REFRESH_TOKEN_TYPE,
        secret_key=secret_key,
        ttl=ttl,
    )


@dataclass(frozen=True)
class DecodedToken:
    subject: uuid.UUID
    role: str
    token_type: str
    jti: str
    expires_at: datetime


def decode_token(token: str, *, secret_key: str, expected_type: str) -> DecodedToken:
    """Verify signature, issuer, audience, expiry and token type."""
    if not token:
        raise TokenError("missing token")
    try:
        payload = jwt.decode(
            token,
            secret_key,
            algorithms=[ALGORITHM],
            audience=TOKEN_AUDIENCE,
            issuer=TOKEN_ISSUER,
            options={"require": ["sub", "typ", "jti", "exp", "iat"]},
        )
    except jwt.PyJWTError as exc:  # signature, expiry, audience, malformed
        raise TokenError("invalid or expired token") from exc

    if payload.get("typ") != expected_type:
        raise TokenError("unexpected token type")
    try:
        subject = uuid.UUID(str(payload["sub"]))
        expires_at = datetime.fromtimestamp(int(payload["exp"]), tz=UTC)
    except (ValueError, KeyError, TypeError) as exc:
        raise TokenError("invalid token claims") from exc

    return DecodedToken(
        subject=subject,
        role=str(payload.get("role", "")),
        token_type=expected_type,
        jti=str(payload["jti"]),
        expires_at=expires_at,
    )


# ---------------------------------------------------------------------------
# Opaque tokens (share links, session identifiers)
# ---------------------------------------------------------------------------


def new_opaque_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """Digest used at rest for opaque bearer tokens."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_fingerprint(token: str, length: int = 8) -> str:
    """Short, non-reversible prefix for display in the owner's UI."""
    return hash_token(token)[:length]
