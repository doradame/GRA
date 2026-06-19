"""add monitoring fields and service health check

Revision ID: 20260619_add_monitoring_fields
Revises: 20260619_0008
Create Date: 2026-06-19 19:05:08.753729

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260619_add_monitoring_fields"
down_revision = "20260619_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IngestionJob extensions
    op.add_column('ingestion_jobs', sa.Column('started_parsing_at', sa.DateTime(), nullable=True))
    op.add_column('ingestion_jobs', sa.Column('completed_parsing_at', sa.DateTime(), nullable=True))
    op.add_column('ingestion_jobs', sa.Column('started_chunking_at', sa.DateTime(), nullable=True))
    op.add_column('ingestion_jobs', sa.Column('completed_chunking_at', sa.DateTime(), nullable=True))
    op.add_column('ingestion_jobs', sa.Column('started_embedding_at', sa.DateTime(), nullable=True))
    op.add_column('ingestion_jobs', sa.Column('completed_embedding_at', sa.DateTime(), nullable=True))
    op.add_column('ingestion_jobs', sa.Column('started_vector_indexing_at', sa.DateTime(), nullable=True))
    op.add_column('ingestion_jobs', sa.Column('completed_vector_indexing_at', sa.DateTime(), nullable=True))
    op.add_column('ingestion_jobs', sa.Column('started_graph_indexing_at', sa.DateTime(), nullable=True))
    op.add_column('ingestion_jobs', sa.Column('completed_graph_indexing_at', sa.DateTime(), nullable=True))
    op.add_column('ingestion_jobs', sa.Column('chunk_count', sa.Integer(), nullable=True))
    op.add_column('ingestion_jobs', sa.Column('entity_count', sa.Integer(), nullable=True))
    op.add_column('ingestion_jobs', sa.Column('relation_count', sa.Integer(), nullable=True))
    op.add_column('ingestion_jobs', sa.Column('input_tokens', sa.Integer(), nullable=True))
    op.add_column('ingestion_jobs', sa.Column('output_tokens', sa.Integer(), nullable=True))
    op.add_column('ingestion_jobs', sa.Column('cost_estimate_usd', sa.Float(), nullable=True))

    # QueryLog extensions
    op.add_column('query_logs', sa.Column('tool_used', sa.String(length=32), nullable=True))
    op.add_column('query_logs', sa.Column('iteration_count', sa.Integer(), nullable=True))
    op.add_column('query_logs', sa.Column('input_tokens', sa.Integer(), nullable=True))
    op.add_column('query_logs', sa.Column('output_tokens', sa.Integer(), nullable=True))
    op.add_column('query_logs', sa.Column('cost_estimate_usd', sa.Float(), nullable=True))

    # ServiceHealthCheck
    op.create_table(
        'service_health_checks',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('service', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('last_check_at', sa.DateTime(), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('service'),
    )
    op.create_index(op.f('ix_service_health_checks_service'), 'service_health_checks', ['service'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_service_health_checks_service'), table_name='service_health_checks')
    op.drop_table('service_health_checks')

    op.drop_column('query_logs', 'cost_estimate_usd')
    op.drop_column('query_logs', 'output_tokens')
    op.drop_column('query_logs', 'input_tokens')
    op.drop_column('query_logs', 'iteration_count')
    op.drop_column('query_logs', 'tool_used')

    op.drop_column('ingestion_jobs', 'cost_estimate_usd')
    op.drop_column('ingestion_jobs', 'output_tokens')
    op.drop_column('ingestion_jobs', 'input_tokens')
    op.drop_column('ingestion_jobs', 'relation_count')
    op.drop_column('ingestion_jobs', 'entity_count')
    op.drop_column('ingestion_jobs', 'chunk_count')
    op.drop_column('ingestion_jobs', 'completed_graph_indexing_at')
    op.drop_column('ingestion_jobs', 'started_graph_indexing_at')
    op.drop_column('ingestion_jobs', 'completed_vector_indexing_at')
    op.drop_column('ingestion_jobs', 'started_vector_indexing_at')
    op.drop_column('ingestion_jobs', 'completed_embedding_at')
    op.drop_column('ingestion_jobs', 'started_embedding_at')
    op.drop_column('ingestion_jobs', 'completed_chunking_at')
    op.drop_column('ingestion_jobs', 'started_chunking_at')
    op.drop_column('ingestion_jobs', 'completed_parsing_at')
    op.drop_column('ingestion_jobs', 'started_parsing_at')
