"""add document description and category

Revision ID: 20260619_0007
Revises: 20260619_0006
Create Date: 2026-06-19
"""

from alembic import op
import sqlalchemy as sa

revision = "20260619_0007"
down_revision = "20260619_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("category", sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "category")
    op.drop_column("documents", "description")
