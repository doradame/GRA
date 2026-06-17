"""add chunk metadata

Revision ID: 20260617_0003
Revises: 20260617_0002
Create Date: 2026-06-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260617_0003"
down_revision: Union[str, None] = "20260617_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("chunks", sa.Column("text_hash", sa.String(length=64), nullable=True))
    op.add_column("chunks", sa.Column("token_count", sa.Integer(), nullable=True))
    op.add_column("chunks", sa.Column("section_title", sa.String(length=512), nullable=True))
    op.create_index(op.f("ix_chunks_text_hash"), "chunks", ["text_hash"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_chunks_text_hash"), table_name="chunks")
    op.drop_column("chunks", "section_title")
    op.drop_column("chunks", "token_count")
    op.drop_column("chunks", "text_hash")
