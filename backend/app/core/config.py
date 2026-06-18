from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@db:5432/insurance_graph_rag"
    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "changeme"
    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "insurance_chunks"
    qdrant_enable_native_sparse: bool = False
    qdrant_dense_vector_name: str = "dense"
    qdrant_sparse_vector_name: str = "text_sparse"
    qdrant_upsert_batch_size: int = 500
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "documents"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-large"
    embedding_dimensions: int = 3072
    embedding_batch_size: int = 96
    enable_ocr: bool = False
    min_text_chars_for_ocr: int = 100
    max_graph_extraction_chunks: int = 48
    retrieval_oversampling_factor: int = 3
    retrieval_lexical_weight: float = 0.15
    retrieval_score_threshold: float = 0.25
    secret_key: str = "supersecretchangeme"
    access_token_expire_minutes: int = 60
    frontend_admin_url: str = "http://localhost:5173"
    llm_temperature: float = 0.1
    mcp_api_key: str = "mcpsecret"
    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/0"
    librechat_api_key: str = "changeme"
    auto_create_tables: bool = True

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
