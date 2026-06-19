import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text, Integer, ForeignKey, Boolean, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base


def generate_uuid():
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("created_by", "content_hash", name="uq_documents_created_by_content_hash"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String(512), nullable=False)
    content_hash = Column(String(64), nullable=True, index=True)
    content_type = Column(String(128), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    storage_key = Column(String(512), nullable=False)
    parser = Column(String(128), nullable=True)
    page_count = Column(Integer, nullable=True)
    text_chars = Column(Integer, nullable=True)
    ocr_used = Column(Boolean, default=False)
    status = Column(String(64), default="uploaded")  # uploaded, parsing, chunking, embedding, vector_indexing, graph_indexing, completed, error
    error_message = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_id_chunk_index"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    text_hash = Column(String(64), nullable=True, index=True)
    token_count = Column(Integer, nullable=True)
    section_title = Column(String(512), nullable=True)
    char_start = Column(Integer, nullable=True)
    char_end = Column(Integer, nullable=True)
    page_start = Column(Integer, nullable=True)
    page_end = Column(Integer, nullable=True)
    qdrant_point_id = Column(String(64), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class QueryLog(Base):
    __tablename__ = "query_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source = Column(String(32), nullable=False, default="api", index=True)  # librechat, mcp, admin, api
    user_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    user_email = Column(String(255), nullable=True)
    query = Column(Text, nullable=False)
    intent = Column(String(32), nullable=True, index=True)  # factual, relational, summary, direct
    reasoning = Column(Text, nullable=True)
    answer = Column(Text, nullable=True)
    citation_count = Column(Integer, default=0)
    error = Column(Text, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(String(255), nullable=True, index=True)
    status = Column(String(64), default="queued", index=True)
    phase = Column(String(64), default="queued")
    progress = Column(Integer, default=0)
    retry_count = Column(Integer, default=0)
    error_code = Column(String(128), nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
