"""Create a user account directly in the database, bypassing the users API.

    uv run scripts/create_user.py admin@firma.cz --role Admin
    uv run scripts/create_user.py jana@firma.cz --role Member --password "s3cret!"

Accounts are otherwise provisioned through ``POST /users`` (see
``law_agent.api.routers.users``), which requires an existing admin's token --
this script exists to create the first admin, or to add one when the API
itself is unreachable. Prompts for the password (hidden input) when
``--password`` is not given, so it never lands in shell history.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from dotenv import load_dotenv

from law_agent.api.auth.security import hash_password
from law_agent.db import RoleRepository, UserRepository, session_scope
from law_agent.users.models import DuplicateUserError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("email")
    parser.add_argument(
        "--role", default="Member", help="an existing role's name, e.g. Admin or Member"
    )
    parser.add_argument(
        "--password", help="prompted for (hidden) if omitted, so it never lands in shell history"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)

    password = args.password or getpass.getpass("Password: ")
    if not password:
        print("password must not be empty", file=sys.stderr)
        return 2

    with session_scope() as session:
        role = RoleRepository(session).get_by_name(args.role)
        if role is None:
            print(f"no role named {args.role!r}", file=sys.stderr)
            return 2
        try:
            user = UserRepository(session).create(
                email=args.email,
                password_hash=hash_password(password),
                role_id=role.id,
            )
        except DuplicateUserError as error:
            print(error, file=sys.stderr)
            return 1
        session.commit()

    print(f"created {user.email} (role={role.name}) id={user.id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
