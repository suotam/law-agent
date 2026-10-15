"""users.is_active: soft delete for accounts

Revision ID: 0006_users_is_active
Revises: 0005_access_control
Create Date: 2026-09-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_users_is_active"
down_revision = "0005_access_control"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default so the existing rows all start active.
    op.add_column(
        "users",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("users", "is_active")
