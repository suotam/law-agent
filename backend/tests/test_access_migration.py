"""The 0005 migration: new tables, and the users.role -> role_id backfill."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from law_agent.config import settings

REPO_ROOT = Path(__file__).resolve().parent.parent
_BACKFILL_DATABASE = "law_agent_test_access_migration"
_DOWNGRADE_DATABASE = "law_agent_test_downgrade_migration"


@pytest.fixture
def pre_migration_engine() -> Engine:
    """A throwaway database migrated only up to 0004, so a legacy ``role``
    row can be inserted before 0005 backfills it."""
    admin_url = make_url(settings.database_url).set(database="postgres")
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        connection = admin.connect()
    except OperationalError:
        admin.dispose()
        pytest.skip("Postgres is not running (docker compose up -d postgres)")

    with connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{_BACKFILL_DATABASE}" WITH (FORCE)'))
        connection.execute(text(f'CREATE DATABASE "{_BACKFILL_DATABASE}"'))
    admin.dispose()

    test_url = make_url(settings.database_url).set(database=_BACKFILL_DATABASE)
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", test_url.render_as_string(hide_password=False))
    command.upgrade(config, "0004_document_conversation")

    engine = create_engine(test_url)
    yield engine
    engine.dispose()

    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{_BACKFILL_DATABASE}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture
def pre_0007_engine() -> Engine:
    """A throwaway database migrated only up to 0006, so a document write
    grant can be inserted before 0007 converts it to read."""
    admin_url = make_url(settings.database_url).set(database="postgres")
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        connection = admin.connect()
    except OperationalError:
        admin.dispose()
        pytest.skip("Postgres is not running (docker compose up -d postgres)")

    with connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{_DOWNGRADE_DATABASE}" WITH (FORCE)'))
        connection.execute(text(f'CREATE DATABASE "{_DOWNGRADE_DATABASE}"'))
    admin.dispose()

    test_url = make_url(settings.database_url).set(database=_DOWNGRADE_DATABASE)
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", test_url.render_as_string(hide_password=False))
    command.upgrade(config, "0006_users_is_active")

    engine = create_engine(test_url)
    yield engine
    engine.dispose()

    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{_DOWNGRADE_DATABASE}" WITH (FORCE)'))
    admin.dispose()


def test_the_migration_backfills_role_id_from_the_legacy_role_column(
    pre_migration_engine: Engine,
) -> None:
    admin_id, member_id = uuid4(), uuid4()
    with pre_migration_engine.connect() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, email, password_hash, role) "
                "VALUES (:id, :email, 'hash', :role)"
            ),
            [
                {"id": admin_id, "email": "stary-admin@firma.cz", "role": "admin"},
                {"id": member_id, "email": "stary-member@firma.cz", "role": "member"},
            ],
        )
        connection.commit()

    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    config.set_main_option(
        "sqlalchemy.url", pre_migration_engine.url.render_as_string(hide_password=False)
    )
    command.upgrade(config, "0005_access_control")

    with pre_migration_engine.connect() as connection:
        rows = dict(
            connection.execute(
                text("SELECT u.email, r.name FROM users u JOIN roles r ON r.id = u.role_id")
            ).all()
        )
    assert rows["stary-admin@firma.cz"] == "Admin"
    assert rows["stary-member@firma.cz"] == "Member"


def test_seeded_roles_have_the_expected_shape(db_engine: Engine) -> None:
    inspector = inspect(db_engine)
    assert {"roles", "role_capabilities", "groups", "group_members", "acl_entries"} <= set(
        inspector.get_table_names()
    )

    with db_engine.connect() as connection:
        # Scoped to the two seeded names rather than the whole table: other
        # tests commit their own roles, so a strict equality would depend on
        # which tests ran first.
        seeded = dict(
            connection.execute(
                text("SELECT name, is_superuser FROM roles WHERE name IN ('Admin', 'Member')")
            ).all()
        )
    assert seeded == {"Admin": True, "Member": False}


def test_0007_downgrades_document_write_grants_to_read(pre_0007_engine: Engine) -> None:
    """Verify that the 0007 migration converts any existing document write
    grants to read. We use an isolated database at 0006 to insert a test row
    before running the 0007 migration."""
    # Insert a document write grant while at 0006
    with pre_0007_engine.begin() as connection:
        connection.execute(
            text(
                "insert into acl_entries "
                "(id, resource_type, resource_id, principal_type, principal_id, permission) "
                "values (gen_random_uuid(), 'document', gen_random_uuid(), 'user', gen_random_uuid(), 'write')"
            )
        )

    # Upgrade to 0007 (which should convert the write to read)
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    config.set_main_option(
        "sqlalchemy.url", pre_0007_engine.url.render_as_string(hide_password=False)
    )
    command.upgrade(config, "0007_document_grants_read_only")

    # Verify the write grant was converted to read
    with pre_0007_engine.connect() as connection:
        rows = connection.execute(
            text("select permission from acl_entries where resource_type = 'document'")
        ).fetchall()
    assert len(rows) > 0
    assert all(row.permission == "read" for row in rows)
