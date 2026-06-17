"""Add chunk page metadata.

Revision ID: 20260617_0005
Revises: 20260617_0004
Create Date: 2026-06-17
"""

from alembic import op
import sqlalchemy as sa


revision = "20260617_0005"
down_revision = "20260617_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chunks", sa.Column("char_start", sa.Integer(), nullable=True))
    op.add_column("chunks", sa.Column("char_end", sa.Integer(), nullable=True))
    op.add_column("chunks", sa.Column("page_start", sa.Integer(), nullable=True))
    op.add_column("chunks", sa.Column("page_end", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("chunks", "page_end")
    op.drop_column("chunks", "page_start")
    op.drop_column("chunks", "char_end")
    op.drop_column("chunks", "char_start")
