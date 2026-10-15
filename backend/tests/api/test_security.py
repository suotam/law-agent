"""Hashing and token minting: the two primitives the whole auth layer rests on."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest

from law_agent.api.auth.security import (
    ALGORITHM,
    TokenClaims,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from law_agent.config import settings


def test_a_password_verifies_against_its_own_hash() -> None:
    password_hash = hash_password("tajne-heslo")

    assert password_hash != "tajne-heslo"
    assert verify_password("tajne-heslo", password_hash)
    assert not verify_password("jine-heslo", password_hash)


def test_a_token_round_trips_identity() -> None:
    user_id = uuid4()

    claims = decode_access_token(create_access_token(user_id))

    assert claims == TokenClaims(user_id=user_id)


def test_a_token_signed_with_another_key_is_rejected() -> None:
    forged = jwt.encode({"sub": str(uuid4())}, "not-our-secret", algorithm=ALGORITHM)

    with pytest.raises(jwt.PyJWTError):
        decode_access_token(forged)


def test_an_expired_token_is_rejected() -> None:
    expired = jwt.encode(
        {"sub": str(uuid4()), "exp": datetime.now(UTC) - timedelta(minutes=1)},
        settings.jwt_secret.get_secret_value(),
        algorithm=ALGORITHM,
    )

    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(expired)
