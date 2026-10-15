"""folders and documents

Revision ID: 0001_documents_and_folders
Revises:
Create Date: 2026-08-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_documents_and_folders"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "folders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "parent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("folders.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ux_folders_sibling_name", "folders", ["parent_id", "name"], unique=True)
    # Partial, because Postgres does not consider two NULLs equal: without it
    # the index above would let two root folders share a name.
    op.create_index(
        "ux_folders_root_name",
        "folders",
        ["name"],
        unique=True,
        postgresql_where=sa.text("parent_id IS NULL"),
    )

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("namespace", sa.Text(), nullable=False),
        sa.Column(
            "folder_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("folders.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("mime", sa.Text(), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("blob_sha256", sa.Text(), nullable=False),
        sa.Column("uploaded_by", sa.Text(), nullable=True),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ux_documents_folder_blob", "documents", ["folder_id", "blob_sha256"], unique=True
    )
    op.create_index("ix_documents_blob_sha256", "documents", ["blob_sha256"])


def downgrade() -> None:
    op.drop_table("documents")
    op.drop_table("folders")
