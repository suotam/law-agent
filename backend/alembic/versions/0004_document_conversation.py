"""documents.conversation_id

Revision ID: 0004_document_conversation
Revises: 0003_users
Create Date: 2026-08-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_document_conversation"
down_revision = "0003_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_documents_conversation_id",
        "documents",
        "conversations",
        ["conversation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_documents_conversation_id", "documents", ["conversation_id"])
    # Rows written before this column existed already know their conversation
    # through the message they hang off.
    op.execute(
        """
        UPDATE documents
        SET conversation_id = messages.conversation_id
        FROM messages
        WHERE documents.message_id = messages.id
        """
    )


def downgrade() -> None:
    op.drop_index("ix_documents_conversation_id", table_name="documents")
    op.drop_constraint("fk_documents_conversation_id", "documents", type_="foreignkey")
    op.drop_column("documents", "conversation_id")
