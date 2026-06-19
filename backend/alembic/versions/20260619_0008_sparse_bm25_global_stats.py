"""add global BM25 vocabulary table and per-document sparse term counts

Revision ID: 20260619_0008
Revises: 20260619_0007
Create Date: 2026-06-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260619_0008"
down_revision = "20260619_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("sparse_term_counts", postgresql.JSONB(), nullable=True))
    op.add_column("documents", sa.Column("sparse_total_tokens", sa.Integer(), nullable=True))

    # sparse_terms può già esistere se AUTO_CREATE_TABLES/create_all l'ha creata prima che
    # questa migrazione girasse (es. dopo un riavvio del backend con il nuovo modello SparseTerm
    # ma prima di applicare la migrazione): la rendiamo idempotente invece di fallire.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "sparse_terms" not in inspector.get_table_names():
        op.create_table(
            "sparse_terms",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("term", sa.String(length=128), nullable=False),
        )
    existing_indexes = {ix["name"] for ix in inspector.get_indexes("sparse_terms")} if "sparse_terms" in inspector.get_table_names() else set()
    if "ix_sparse_terms_term" not in existing_indexes:
        op.create_index("ix_sparse_terms_term", "sparse_terms", ["term"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_sparse_terms_term", table_name="sparse_terms")
    op.drop_table("sparse_terms")
    op.drop_column("documents", "sparse_total_tokens")
    op.drop_column("documents", "sparse_term_counts")
