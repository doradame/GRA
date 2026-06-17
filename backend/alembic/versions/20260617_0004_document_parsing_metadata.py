"""add document parsing metadata

Revision ID: 20260617_0004
Revises: 20260617_0003
Create Date: 2026-06-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260617_0004"
down_revision: Union[str, None] = "20260617_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("parser", sa.String(length=128), nullable=True))
    op.add_column("documents", sa.Column("page_count", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("text_chars", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("ocr_used", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "ocr_used")
    op.drop_column("documents", "text_chars")
    op.drop_column("documents", "page_count")
    op.drop_column("documents", "parser")
