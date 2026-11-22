"""Persist stable auth sessions and a user-wide revocation version.

Revision ID: 20261109_0002
Revises: 20261108_0001
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "20261109_0002"
down_revision: str = "20261108_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("session_version", sa.Integer(), server_default=sa.text("0"),
                           nullable=False),
    )
    op.add_column("refresh_tokens", sa.Column("session_id", sa.UUID(), nullable=True))
    op.execute(sa.text("UPDATE refresh_tokens SET session_id = id WHERE session_id IS NULL"))
    op.alter_column(
        "refresh_tokens", "session_id", existing_type=sa.UUID(), nullable=False,
        server_default=sa.text("gen_random_uuid()"),
    )
    op.create_index(
        "ix_refresh_tokens_active_session", "refresh_tokens", ["session_id"], unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_refresh_tokens_active_session", table_name="refresh_tokens")
    op.drop_column("refresh_tokens", "session_id")
    op.drop_column("users", "session_version")
