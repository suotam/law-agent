"""Login, and the check a client runs against the token it already holds."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from law_agent.api.auth.dependencies import CurrentUser
from law_agent.api.auth.security import create_access_token, hash_password, verify_password
from law_agent.api.schemas import (
    LoginRequest,
    LoginResponse,
    PasswordChange,
    UserResponse,
)
from law_agent.db import RoleRepository, UserRepository, session_scope

router = APIRouter(prefix="/auth", tags=["auth"])

# A second router so the password change lives with the other account
# endpoints in this module while keeping the /me URL the member-facing
# resources share (me_org_files.py).
me_router = APIRouter(prefix="/me", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest) -> LoginResponse:
    with session_scope() as session:
        user = UserRepository(session).get_by_email(payload.email)

    # One message for both failures: distinguishing them would tell an attacker
    # which addresses are registered. A deactivated account fails here too --
    # same message, it may not authenticate regardless of the password.
    if (
        user is None
        or not user.is_active
        or not verify_password(payload.password, user.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid email or password"
        )

    return LoginResponse(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserResponse)
def me(user: CurrentUser) -> UserResponse:
    """Is this token still good, and whose is it.

    The row is read rather than the claims echoed back: a token outlives the
    account it was issued for, and a role changed by an admin would otherwise
    stay stale in the client until the token expired. A token whose user is
    gone is not authenticated, not a 404 -- the caller asked about itself.
    """
    with session_scope() as session:
        account = UserRepository(session).get(user.user_id)
        if account is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        # The FK from users.role_id to roles guarantees this is never None.
        role = RoleRepository(session).get(account.role_id)

    return UserResponse.from_domain(account, role)  # type: ignore[arg-type]


@me_router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_own_password(user: CurrentUser, payload: PasswordChange) -> None:
    """Self-service password change.

    The current password is required even though the token already proves
    identity: a token valid until it expires (there is no revocation) must not
    be enough on its own to permanently take an account over. The token stays
    valid after the change -- stateless, no revocation; this proves knowledge,
    it does not re-authenticate the session."""
    with session_scope() as session:
        account = UserRepository(session).get(user.user_id)
        if account is None or not verify_password(payload.current_password, account.password_hash):
            # One message, like login: the failure must not distinguish "wrong
            # password" from anything else about the account.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="current password is incorrect"
            )
        UserRepository(session).set_password(account.id, hash_password(payload.new_password))
        session.commit()
