import asyncio
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:15432/graph_rag_test")
os.environ.setdefault("NEO4J_URI", "bolt://localhost:17687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "testpassword")
os.environ.setdefault("QDRANT_URL", "http://localhost:16333")
os.environ.setdefault("QDRANT_COLLECTION", f"e2e_chunks_{uuid.uuid4().hex}")
os.environ.setdefault("QDRANT_ENABLE_NATIVE_SPARSE", "true")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:19000")
os.environ.setdefault("MINIO_ACCESS_KEY", "minioadmin")
os.environ.setdefault("MINIO_SECRET_KEY", "minioadmin")
os.environ.setdefault("MINIO_BUCKET", f"e2e-documents-{uuid.uuid4().hex[:8]}")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:16379/0")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:16379/0")

from sqlalchemy import select  # noqa: E402

from app.core.auth import get_password_hash  # noqa: E402
from app.core.database import Base  # noqa: E402
from app.models.models import Chunk, Document, IngestionJob, User  # noqa: E402
from app.services.graph_store import graph_store  # noqa: E402
from app.services.ingestion import create_document, process_document  # noqa: E402
from app.services.storage import storage  # noqa: E402
from app.services.vector_store import vector_store  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402


async def _wait_for_services(timeout_seconds: int = 120) -> None:
    deadline = time.time() + timeout_seconds
    last_error = None
    while time.time() < deadline:
        try:
            engine = create_async_engine(os.environ["DATABASE_URL"])
            async with engine.begin() as conn:
                await conn.run_sync(lambda sync_conn: sync_conn.exec_driver_sql("SELECT 1"))
            await engine.dispose()
            vector_store.client.get_collections()
            graph_store.get_stats()
            storage.client.bucket_exists(storage.bucket)
            return
        except Exception as exc:
            last_error = exc
            await asyncio.sleep(2)
    raise RuntimeError(f"Services did not become ready: {last_error}")


async def main() -> None:
    await _wait_for_services()

    engine = create_async_engine(os.environ["DATABASE_URL"], echo=False, future=True)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as db:
        user = User(
            email=f"e2e-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password=get_password_hash("secret"),
            is_active=True,
            is_admin=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        doc = await create_document(
            db=db,
            filename="policy.txt",
            content_type="text/plain",
            data=(
                b"POLICY X\n\n"
                b"Policy X requires approval from the risk team before publication.\n\n"
                b"Policy Y excludes expired contracts from automatic renewal."
            ),
            user_id=str(user.id),
        )

    await process_document(
        document_id=str(doc.id),
        filename=doc.filename,
        content_type=doc.content_type,
        storage_key=doc.storage_key,
        user_id=str(user.id),
        task_id=f"e2e-{uuid.uuid4()}",
        retry_count=0,
    )

    async with SessionLocal() as db:
        document = await db.get(Document, doc.id)
        chunk_count = (
            await db.execute(select(Chunk).where(Chunk.document_id == doc.id))
        ).scalars().all()
        jobs = (
            await db.execute(select(IngestionJob).where(IngestionJob.document_id == doc.id))
        ).scalars().all()

    vector_count = vector_store.count(user_id=str(user.id))
    graph_stats = graph_store.get_stats(user_id=str(user.id))

    assert document is not None
    assert document.status == "completed"
    assert document.parser == "text"
    assert document.text_chars and document.text_chars > 0
    assert len(chunk_count) > 0
    assert jobs and jobs[-1].status == "completed"
    assert vector_count == len(chunk_count)
    assert graph_stats["documents"] == 1
    assert graph_stats["chunks"] == len(chunk_count)

    print(
        {
            "document_id": str(doc.id),
            "chunks": len(chunk_count),
            "vectors": vector_count,
            "graph": graph_stats,
            "status": document.status,
        }
    )

    vector_store.reset_collection()
    graph_store.reset()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
