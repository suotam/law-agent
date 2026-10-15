"""Who is calling, and may they.

Every non-auth endpoint depends on :func:`get_current_user`; management routes
layer :func:`require_capability` or :func:`require_superuser` on top. Both
re-read the caller's role from the database on every request -- see
:func:`law_agent.access.service.role_for_user` -- so a role edited by an admin
takes effect on the very next request, not after the caller's token expires.

Replacing the token issuer later (Keycloak, OIDC) means rewriting
:func:`law_agent.api.auth.security.decode_access_token` -- the checks spread
across the routers do not change shape.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from law_agent.access.models import RoleCapability
from law_agent.access.service import role_for_user
from law_agent.api.auth.security import TokenClaims, decode_access_token
from law_agent.db import UserRepository, session_scope

# auto_error=False so a missing header lands in our own 401 with the same body
# as an invalid one, rather than in Starlette's 403.
_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_scheme)],
) -> TokenClaims:
    if credentials is None:
        raise _unauthenticated()
    try:
        claims = decode_access_token(credentials.credentials)
    except jwt.PyJWTError as error:
        raise _unauthenticated() from error
    # The token proves identity, the database proves the identity still holds:
    # a soft-deleted (deactivated) account's existing token must die on its
    # very next request, which no token-only check can do. One indexed PK
    # lookup per request, the same cost class the capability checks already
    # accepted.
    with session_scope() as session:
        account = UserRepository(session).get(claims.user_id)
    if account is None or not account.is_active:
        raise _unauthenticated()
    return claims


CurrentUser = Annotated[TokenClaims, Depends(get_current_user)]


def require_capability(capability: RoleCapability) -> Callable[[TokenClaims], TokenClaims]:
    """A dependency that lets a caller through if their role is a superuser
    role or holds ``capability``.

    A factory rather than a plain dependency: FastAPI dependencies take no
    arguments of their own, so the capability has to be closed over.
    """

    def check(user: CurrentUser) -> TokenClaims:
        role = role_for_user(user.user_id)
        if role is None or not (role.is_superuser or capability in role.capabilities):
            raise _forbidden()
        return user

    return check


def require_any_capability(*capabilities: RoleCapability) -> Callable[[TokenClaims], TokenClaims]:
    """Like :func:`require_capability`, but passes if the caller's role holds
    any one of ``capabilities`` -- the floor check for an endpoint whose
    finer-grained authorization happens inside the handler (see ``acl.py``,
    where the specific capability needed depends on the request body).
    """

    def check(user: CurrentUser) -> TokenClaims:
        role = role_for_user(user.user_id)
        if role is None or not (
            role.is_superuser or any(capability in role.capabilities for capability in capabilities)
        ):
            raise _forbidden()
        return user

    return check


def require_superuser(user: CurrentUser) -> TokenClaims:
    """Role and capability administration itself is gated on this, never on
    a capability -- a capability could otherwise let a role grant itself
    more capabilities than it started with."""
    role = role_for_user(user.user_id)
    if role is None or not role.is_superuser:
        raise _forbidden()
    return user


def _forbidden() -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient capability")


def _unauthenticated() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
