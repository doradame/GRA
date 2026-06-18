import uuid
import hashlib
import logging
import re
from datetime import datetime
import tiktoken
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import delete, select
from qdrant_client.models import PointStruct

from app.core.config import get_settings
from app.models.models import Document, Chunk, IngestionJob
from app.services.storage import storage
from app.services.parsing import extract_document
from app.services.chunking import chunk_text
from app.services.embeddings import embed_texts
from app.services.vector_store import vector_store
from app.services.graph_store import graph_store
from app.services.extraction import extract_entities_relations
from app.services.sparse_vectors import build_sparse_vector, tokenize_sparse

logger = logging.getLogger(__name__)

STATUS_UPLOADED = "uploaded"
STATUS_PARSING = "parsing"
STATUS_CHUNKING = "chunking"
STATUS_EMBEDDING = "embedding"
STATUS_VECTOR_INDEXING = "vector_indexing"
STATUS_GRAPH_INDEXING = "graph_indexing"
STATUS_COMPLETED = "completed"
STATUS_ERROR = "error"
SCHEDULABLE_STATUSES = {STATUS_UPLOADED, STATUS_ERROR}

PHASE_PROGRESS = {
    STATUS_UPLOADED: 0,
    STATUS_PARSING: 10,
    STATUS_CHUNKING: 25,
    STATUS_EMBEDDING: 45,
    STATUS_VECTOR_INDEXING: 65,
    STATUS_GRAPH_INDEXING: 80,
    STATUS_COMPLETED: 100,
    STATUS_ERROR: 100,
}


def _safe_filename(filename: str) -> str:
    name = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].strip() or "unnamed"
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name)
    return name[:180] or "unnamed"


def _stable_uuid(*parts: object) -> str:
    raw = ":".join(str(part) for part in parts)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"graph-rag-assistant:{raw}"))


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _token_count(text: str, model: str | None = None) -> int:
    try:
        encoding = tiktoken.encoding_for_model(model or get_settings().embedding_model)
        return len(encoding.encode(text))
    except Exception:
        # tiktoken may lazily download encodings in fresh environments. Keep ingestion offline-safe.
        words = len(text.split())
        return max(1, int(words * 1.35))


def _infer_section_title(text: str) -> str | None:
    for line in text.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        if len(candidate) <= 120 and (candidate.isupper() or not candidate.endswith((".", ":", ";", ","))):
            return candidate[:120]
        return None
    return None


def _find_chunk_span(text: str, chunk: str, start_from: int = 0) -> tuple[int, int]:
    start = text.find(chunk, start_from)
    if start == -1 and start_from:
        start = text.find(chunk)
    if start == -1:
        return start_from, start_from + len(chunk)
    return start, start + len(chunk)


def _pages_for_span(pages: list | None, start: int, end: int) -> tuple[int | None, int | None]:
    if not pages:
        return None, None
    matching = [
        page.page
        for page in pages
        if page.end_char >= start and page.start_char <= end
    ]
    if not matching:
        return None, None
    return min(matching), max(matching)


async def _set_document_status(
    db: AsyncSession,
    doc: Document,
    status: str,
    error_message: str | None = None,
    job: IngestionJob | None = None,
    progress: int | None = None,
) -> None:
    doc.status = status
    doc.error_message = error_message
    if job is not None:
        job.phase = status
        job.progress = PHASE_PROGRESS.get(status, progress or job.progress or 0) if progress is None else progress
        job.error_message = error_message
        if status == STATUS_ERROR:
            job.status = STATUS_ERROR
            job.error_code = "ingestion_failed"
            job.completed_at = datetime.utcnow()
        elif status == STATUS_COMPLETED:
            job.status = STATUS_COMPLETED
            job.error_code = None
            job.completed_at = datetime.utcnow()
        else:
            job.status = "running"
            job.error_code = None
            if job.started_at is None:
                job.started_at = datetime.utcnow()
    await db.commit()
    logger.info("[ingestion] Document %s status=%s", doc.id, status)


async def _get_or_create_job(
    db: AsyncSession,
    document_id: str,
    task_id: str | None,
    retry_count: int,
) -> IngestionJob:
    stmt = select(IngestionJob).where(IngestionJob.document_id == document_id)
    if task_id:
        stmt = stmt.where(IngestionJob.task_id == task_id)
    result = await db.execute(stmt.order_by(IngestionJob.created_at.desc()))
    job = result.scalars().first()
    if job is None:
        job = IngestionJob(
            document_id=document_id,
            task_id=task_id,
            status="running",
            phase=STATUS_UPLOADED,
            progress=0,
            retry_count=retry_count,
            started_at=datetime.utcnow(),
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
    else:
        job.status = "running"
        job.retry_count = retry_count
        job.error_code = None
        job.error_message = None
        if job.started_at is None:
            job.started_at = datetime.utcnow()
        await db.commit()
        await db.refresh(job)
    return job


async def _cleanup_document_artifacts(db: AsyncSession, document_id: str) -> None:
    """Remove derived data so retries can rebuild the document deterministically."""
    logger.info("[ingestion] Cleaning derived artifacts for document_id=%s", document_id)
    await db.execute(delete(Chunk).where(Chunk.document_id == document_id))
    await db.commit()
    try:
        vector_store.delete_by_document(document_id)
    except Exception:
        logger.exception("[ingestion] Failed to delete Qdrant points for document_id=%s", document_id)
    try:
        graph_store.delete_document(document_id)
    except Exception:
        logger.exception("[ingestion] Failed to delete graph data for document_id=%s", document_id)


async def create_document(
    db: AsyncSession,
    filename: str,
    content_type: str,
    data: bytes,
    user_id: str,
) -> Document:
    """Create the initial document record, upload to storage, and return it.

    If a document with the same content hash already exists, the existing record
    is returned immediately and no background processing is scheduled.
    """
    filename = _safe_filename(filename)
    content_hash = hashlib.sha256(data).hexdigest()
    logger.info("[ingestion] Received upload: filename=%s size=%s bytes user=%s", filename, len(data), user_id)
    logger.info("[ingestion] Content hash: %s", content_hash)

    # Deduplication is scoped to the current owner. Cross-user dedupe would leak metadata.
    result = await db.execute(
        select(Document).where(
            Document.content_hash == content_hash,
            Document.created_by == user_id,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        logger.info(
            "[ingestion] Duplicate detected: existing document_id=%s filename=%s status=%s",
            existing.id,
            existing.filename,
            existing.status,
        )
        if existing.status == STATUS_ERROR:
            existing.status = STATUS_UPLOADED
            existing.error_message = None
            await db.commit()
            await db.refresh(existing)
        return existing

    doc_id = str(uuid.uuid4())
    storage_key = f"{user_id}/{doc_id}/{filename}"
    logger.info("[ingestion] Creating new document_id=%s storage_key=%s", doc_id, storage_key)

    # Save to object storage
    logger.info("[ingestion] Uploading to object storage: %s", storage_key)
    storage.upload(storage_key, data, content_type)
    logger.info("[ingestion] Object storage upload complete: %s", storage_key)

    # Create DB record
    doc = Document(
        id=doc_id,
        filename=filename,
        content_hash=content_hash,
        content_type=content_type,
        size_bytes=len(data),
        storage_key=storage_key,
        status=STATUS_UPLOADED,
        created_by=user_id,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    logger.info("[ingestion] Document record created: id=%s status=%s", doc.id, doc.status)
    return doc


async def process_document(
    document_id: str,
    filename: str,
    content_type: str,
    storage_key: str,
    user_id: str,
    task_id: str | None = None,
    retry_count: int = 0,
) -> None:
    """Run the full ingestion pipeline in the background.

    This function creates its own database engine and session so it can be
    executed safely inside a Celery worker process (where each task runs in its
    own event loop).
    """
    logger.info("[ingestion] Background processing started for document_id=%s", document_id)
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False, future=True)
    AsyncSessionLocalTask = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with AsyncSessionLocalTask() as db:
            result = await db.execute(select(Document).where(Document.id == document_id))
            doc = result.scalar_one_or_none()
            if not doc:
                logger.error("[ingestion] Document %s not found in database; aborting", document_id)
                return
            if str(doc.created_by) != str(user_id):
                logger.error("[ingestion] User mismatch for document_id=%s; aborting", document_id)
                return
            if doc.status == STATUS_COMPLETED:
                logger.info("[ingestion] Document %s already completed; skipping", document_id)
                return
            job = await _get_or_create_job(db, document_id, task_id, retry_count)

            try:
                await _cleanup_document_artifacts(db, document_id)

                await _set_document_status(db, doc, STATUS_PARSING, job=job)
                logger.info("[ingestion] Downloading from object storage: %s", storage_key)
                data = storage.download(storage_key)
                logger.info("[ingestion] Downloaded %s bytes for document_id=%s", len(data), document_id)

                logger.info("[ingestion] Extracting text from document_id=%s", document_id)
                parsed = extract_document(
                    filename,
                    data,
                    enable_ocr=settings.enable_ocr,
                    min_text_chars_for_ocr=settings.min_text_chars_for_ocr,
                )
                text = parsed.text.strip()
                doc.parser = parsed.parser
                doc.page_count = parsed.page_count
                doc.text_chars = len(text)
                doc.ocr_used = parsed.ocr_used
                await db.commit()
                logger.info("[ingestion] Extracted %s characters of text from document_id=%s", len(text), document_id)
                if not text:
                    raise ValueError("No extractable text found in document")

                await _set_document_status(db, doc, STATUS_CHUNKING, job=job)
                logger.info("[ingestion] Chunking text for document_id=%s", document_id)
                chunks = chunk_text(text)
                logger.info("[ingestion] Generated %s chunks for document_id=%s", len(chunks), document_id)
                if not chunks:
                    raise ValueError("Document text did not produce any chunks")

                # Build token corpus for BM25 sparse vector IDF computation.
                corpus_tokens = [tokenize_sparse(chunk) for chunk in chunks]
                logger.debug("[ingestion] Built sparse corpus with %s tokenized chunks", len(corpus_tokens))

                # Embed chunks
                await _set_document_status(db, doc, STATUS_EMBEDDING, job=job)
                logger.info("[ingestion] Generating embeddings for %s chunks of document_id=%s", len(chunks), document_id)
                embeddings = await embed_texts(chunks)
                logger.info("[ingestion] Embeddings generated for document_id=%s", document_id)
                if len(embeddings) != len(chunks):
                    raise ValueError(f"Embedding count mismatch: chunks={len(chunks)} embeddings={len(embeddings)}")

                qdrant_points = []
                chunk_records = []
                span_cursor = 0
                for idx, (chunk_text_content, embedding) in enumerate(zip(chunks, embeddings)):
                    text_hash = _hash_text(chunk_text_content)
                    token_count = _token_count(chunk_text_content, settings.embedding_model)
                    section_title = _infer_section_title(chunk_text_content)
                    span_start, span_end = _find_chunk_span(text, chunk_text_content, span_cursor)
                    span_cursor = span_end
                    page_start, page_end = _pages_for_span(parsed.pages, span_start, span_end)
                    chunk_id = _stable_uuid("chunk", document_id, idx, text_hash)
                    qdrant_id = chunk_id

                    chunk_records.append(
                        Chunk(
                            id=chunk_id,
                            document_id=document_id,
                            chunk_index=idx,
                            text=chunk_text_content,
                            text_hash=text_hash,
                            token_count=token_count,
                            section_title=section_title,
                            char_start=span_start,
                            char_end=span_end,
                            page_start=page_start,
                            page_end=page_end,
                            qdrant_point_id=qdrant_id,
                        )
                    )

                    qdrant_points.append(
                        PointStruct(
                            id=qdrant_id,
                            vector=vector_store.build_point_vector(
                                embedding,
                                build_sparse_vector(chunk_text_content, corpus_tokens),
                            ),
                            payload={
                                "chunk_id": chunk_id,
                                "document_id": document_id,
                                "user_id": user_id,
                                "filename": filename,
                                "text": chunk_text_content,
                                "index": idx,
                                "text_hash": text_hash,
                                "token_count": token_count,
                                "section_title": section_title,
                                "char_start": span_start,
                                "char_end": span_end,
                                "page_start": page_start,
                                "page_end": page_end,
                                "document_page_count": parsed.page_count,
                                "status": STATUS_COMPLETED,
                            },
                        )
                    )

                # Bulk insert chunks
                logger.info("[ingestion] Persisting %s chunks to database for document_id=%s", len(chunk_records), document_id)
                db.add_all(chunk_records)
                await db.commit()
                logger.info("[ingestion] Chunks persisted for document_id=%s", document_id)

                # Bulk insert vectors
                if qdrant_points:
                    await _set_document_status(db, doc, STATUS_VECTOR_INDEXING, job=job)
                    logger.info("[ingestion] Upserting %s vectors to Qdrant for document_id=%s", len(qdrant_points), document_id)
                    vector_store.upsert(qdrant_points)
                    logger.info("[ingestion] Vectors upserted for document_id=%s", document_id)

                await _set_document_status(db, doc, STATUS_GRAPH_INDEXING, job=job)
                logger.info("[ingestion] Adding document node to graph: document_id=%s", document_id)
                graph_store.add_document(document_id, filename, content_type, user_id=user_id)
                logger.info("[ingestion] Document node added to graph: document_id=%s", document_id)

                progress_step = max(1, len(chunks) // 20)
                max_graph_extraction_chunks = max(0, settings.max_graph_extraction_chunks)
                for idx, chunk_text_content in enumerate(chunks):
                    text_hash = _hash_text(chunk_text_content)
                    chunk_id = _stable_uuid("chunk", document_id, idx, text_hash)

                    logger.debug("[ingestion] Adding chunk %s/%s to graph for document_id=%s", idx + 1, len(chunks), document_id)
                    graph_store.add_chunk(chunk_id, document_id, chunk_text_content, idx, user_id=user_id)

                    if idx >= max_graph_extraction_chunks:
                        if idx == max_graph_extraction_chunks:
                            logger.info(
                                "[ingestion] Skipping entity extraction after %s chunks for document_id=%s",
                                max_graph_extraction_chunks,
                                document_id,
                            )
                        if (idx + 1) % progress_step == 0 or idx + 1 == len(chunks):
                            graph_progress = 80 + int(((idx + 1) / len(chunks)) * 18)
                            await _set_document_status(db, doc, STATUS_GRAPH_INDEXING, job=job, progress=graph_progress)
                        continue

                    logger.debug("[ingestion] Extracting entities/relations for chunk %s/%s of document_id=%s", idx + 1, len(chunks), document_id)
                    try:
                        extracted = await extract_entities_relations(chunk_text_content)
                    except Exception as extraction_error:
                        logger.warning(
                            "[ingestion] Entity extraction failed for chunk %s/%s of document_id=%s: %s",
                            idx + 1,
                            len(chunks),
                            document_id,
                            extraction_error,
                        )
                        extracted = {"entities": [], "relations": []}
                    entities = extracted.get("entities", [])
                    relations = extracted.get("relations", [])
                    logger.debug(
                        "[ingestion] Chunk %s/%s extracted %s entities and %s relations for document_id=%s",
                        idx + 1,
                        len(chunks),
                        len(entities),
                        len(relations),
                        document_id,
                    )
                    graph_store.add_entities_and_relations(chunk_id, entities, relations)
                    if (idx + 1) % progress_step == 0 or idx + 1 == len(chunks):
                        graph_progress = 80 + int(((idx + 1) / len(chunks)) * 18)
                        await _set_document_status(db, doc, STATUS_GRAPH_INDEXING, job=job, progress=graph_progress)

                await _set_document_status(db, doc, STATUS_COMPLETED, job=job)
                await db.refresh(doc)
                logger.info("[ingestion] Processing completed for document_id=%s status=%s", document_id, doc.status)

            except Exception as e:
                logger.exception("[ingestion] Processing failed for document_id=%s: %s", document_id, e)
                await db.rollback()
                await _cleanup_document_artifacts(db, document_id)
                try:
                    merged = await db.merge(doc)
                    merged_job = await db.merge(job)
                    merged.status = STATUS_ERROR
                    merged.error_message = str(e)[:4000]
                    merged_job.status = STATUS_ERROR
                    merged_job.phase = STATUS_ERROR
                    merged_job.progress = 100
                    merged_job.error_code = type(e).__name__
                    merged_job.error_message = str(e)[:4000]
                    merged_job.completed_at = datetime.utcnow()
                    await db.commit()
                    await db.refresh(merged)
                    logger.info("[ingestion] Marked document_id=%s as error", document_id)
                except Exception:
                    logger.exception("[ingestion] Could not update error status for document_id=%s", document_id)
                raise
    finally:
        logger.info("[ingestion] Disposing database engine for document_id=%s", document_id)
        await engine.dispose()
