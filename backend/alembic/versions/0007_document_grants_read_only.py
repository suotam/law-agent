"""acl_entries: downgrade existing document write grants to read

Documents only ever support 'read' from now on (see the org files access
redesign spec) -- write lives on folders only. No schema change: the
permission column stays a free Text; this just fixes up any row that
predates the rule.

Revision ID: 0007_document_grants_read_only
Revises: 0006_users_is_active
Create Date: 2026-09-05

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_document_grants_read_only"
down_revision = "0006_users_is_active"
branch_labels = None
depends_on = None

_ACL_ENTRIES = sa.table(
    "acl_entries",
    sa.column("resource_type", sa.Text),
    sa.column("permission", sa.Text),
)


def upgrade() -> None:
    op.execute(
        _ACL_ENTRIES.update()
        .where(_ACL_ENTRIES.c.resource_type == "document")
        .where(_ACL_ENTRIES.c.permission == "write")
        .values(permission="read")
    )


def downgrade() -> None:
    # Irreversible by design: which document rows were originally "write"
    # is not recoverable once downgraded.
    pass
