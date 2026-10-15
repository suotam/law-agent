"""Passwords and bearer tokens.

Deliberately stateless: the token carries identity only, and there is no
refresh token and no revocation list. A stolen token is valid until it expires
-- accepted, because the goal is a shape a future OIDC provider can slot into
(bearer JWT, one decode function), not maximal security today.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from pwdlib import PasswordHash
from pydantic import BaseModel, ConfigDict

from law_agent.config import settings

ALGORITHM = "HS256"
"""Not a setting: a deployment that can choose its algorithm can choose ``none``."""

_hasher = PasswordHash.recommended()


class TokenClaims(BaseModel):
    """What a validated token says. The only identity the routers ever see.

    No ``role`` here: capabilities change at runtime (an admin edits
    ``role_capabilities``, or reassigns a user's ``role_id``), and a value
    baked into the token would stay stale until it expired, days later. Every
    capability check re-reads ``role_id -> role_capabilities`` from the
    database instead -- see :func:`law_agent.access.service.role_for_user`.
    """

    model_config = ConfigDict(frozen=True)

    user_id: UUID


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _hasher.verify(password, password_hash)


def create_access_token(user_id: UUID) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(UTC) + timedelta(days=settings.jwt_expiry_days),
    }
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> TokenClaims:
    """Raises:
    jwt.PyJWTError: the token is malformed, expired or signed by someone else.
    """
    payload = jwt.decode(token, settings.jwt_secret.get_secret_value(), algorithms=[ALGORITHM])
    return TokenClaims(user_id=UUID(payload["sub"]))
