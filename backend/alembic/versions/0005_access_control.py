"""access control: roles, capabilities, groups, acl

Revision ID: 0005_access_control
Revises: 0004_document_conversation
Create Date: 2026-09-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_access_control"
down_revision = "0004_document_conversation"
branch_labels = None
depends_on = None

# Fixed so upgrade and downgrade agree on which row is which; only ever
# referenced inside this migration.
_ADMIN_ROLE_ID = "3f6a2c1e-6b8a-4b8b-9b0a-9a4e6a2b0c01"
_MEMBER_ROLE_ID = "3f6a2c1e-6b8a-4b8b-9b0a-9a4e6a2b0c02"


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "role_capabilities",
        sa.Column(
            "role_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("roles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("capability", sa.Text(), primary_key=True),
    )
    op.create_table(
        "groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "group_members",
        sa.Column(
            "group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("groups.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_table(
        "acl_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("resource_type", sa.Text(), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("principal_type", sa.Text(), nullable=False),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ux_acl_entries_resource_principal",
        "acl_entries",
        ["resource_type", "resource_id", "principal_type", "principal_id"],
        unique=True,
    )

    op.execute(
        f"""
        INSERT INTO roles (id, name, is_superuser)
        VALUES
            ('{_ADMIN_ROLE_ID}', 'Admin', true),
            ('{_MEMBER_ROLE_ID}', 'Member', false)
        """
    )

    op.add_column("users", sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.execute(
        f"""
        UPDATE users
        SET role_id = CASE role
            WHEN 'admin' THEN '{_ADMIN_ROLE_ID}'::uuid
            WHEN 'member' THEN '{_MEMBER_ROLE_ID}'::uuid
        END
        """
    )
    op.alter_column("users", "role_id", nullable=False)
    op.create_foreign_key(
        "fk_users_role_id", "users", "roles", ["role_id"], ["id"], ondelete="RESTRICT"
    )
    op.drop_column("users", "role")


def downgrade() -> None:
    op.add_column("users", sa.Column("role", sa.Text(), nullable=True))
    op.execute(
        f"""
        UPDATE users
        SET role = CASE role_id
            WHEN '{_ADMIN_ROLE_ID}' THEN 'admin'
            WHEN '{_MEMBER_ROLE_ID}' THEN 'member'
            ELSE 'member'
        END
        """
    )
    op.alter_column("users", "role", nullable=False)
    op.drop_constraint("fk_users_role_id", "users", type_="foreignkey")
    op.drop_column("users", "role_id")
    op.drop_index("ux_acl_entries_resource_principal", table_name="acl_entries")
    op.drop_table("acl_entries")
    op.drop_table("group_members")
    op.drop_table("groups")
    op.drop_table("role_capabilities")
    op.drop_table("roles")
