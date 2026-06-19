"""add query logs

Revision ID: 20260619_0006
Revises: 20260617_0005
Create Date: 2026-06-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260619_0006"
down_revision = "20260617_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "query_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_email", sa.String(length=255), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(length=32), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("citation_count", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_query_logs_source"), "query_logs", ["source"], unique=False)
    op.create_index(op.f("ix_query_logs_user_id"), "query_logs", ["user_id"], unique=False)
    op.create_index(op.f("ix_query_logs_intent"), "query_logs", ["intent"], unique=False)
    op.create_index(op.f("ix_query_logs_created_at"), "query_logs", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_query_logs_created_at"), table_name="query_logs")
    op.drop_index(op.f("ix_query_logs_intent"), table_name="query_logs")
    op.drop_index(op.f("ix_query_logs_user_id"), table_name="query_logs")
    op.drop_index(op.f("ix_query_logs_source"), table_name="query_logs")
    op.drop_table("query_logs")
