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
from app.services.extraction import extract_relations
from app.services.gliner_extraction import extract_entities as gliner_extract_entities
from app.services.sparse_vectors import tokenize_sparse, weighted_sparse_vector
from app.services.sparse_corpus_stats import (
    apply_document_delta,
    get_global_stats_snapshot,
    get_or_create_term_ids,
    subtract_document_contribution,
)
from app.services.contextual_chunking import generate_chunk_contexts
from app.services.api_usage import estimate_cost_usd

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


def _count_tokens_for_model(texts: list[str], model: str) -> int:
    return sum(_token_count(t, model) for t in texts)


def _infer_section_title(text: str) -> str | None:
    for line in text.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        if len(candidate) <= 120 and (candidate.isupper() or not candidate.endswith((".", ":", ";", ","))):
            return candidate[:120]
        return None
    return None


def _build_document_context(filename: str, category: str | None, description: str | None) -> str:
    """Header riusato per ogni chunk del documento (contextual retrieval).

    Antepone titolo/categoria/descrizione fornita dall'utente al testo del chunk
    SOLO per l'embedding e il vettore sparso: il testo del chunk salvato per le
    citazioni e il contesto LLM resta quello originale, non modificato.
    """
    parts = [f"Documento: {filename}"]
    if category:
        parts.append(f"Categoria: {category}")
    if description:
        parts.append(f"Descrizione: {description.strip()}")
    return "\n".join(parts)


def _build_chunk_embedding_input(
    document_context: str,
    section_title: str | None,
    chunk_text_content: str,
    llm_context: str | None = None,
) -> str:
    parts = [document_context]
    if section_title:
        parts.append(f"Sezione: {section_title}")
    if llm_context:
        parts.append(llm_context)
    parts.append(chunk_text_content)
    return "\n\n".join(parts)


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
    """Remove derived data so retries can rebuild the document deterministically.

    Sottrae anche il contributo BM25 della versione precedente di questo documento dalle
    statistiche globali, prima di azzerarne i chunk: altrimenti un reindex farebbe drift
    via via le statistiche verso l'alto (doppio conteggio). subtract_document_contribution
    refetches il Document fresco invece di fidarsi dell'oggetto del chiamante, perché questa
    funzione è chiamata anche dall'error handler subito dopo un rollback (che può invalidare
    gli attributi già caricati).
    """
    logger.info("[ingestion] Cleaning derived artifacts for document_id=%s", document_id)

    await subtract_document_contribution(db, document_id)
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
    description: str | None = None,
    category: str | None = None,
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
        description=description or None,
        category=category or None,
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
            job.input_tokens = 0
            job.output_tokens = 0
            job.cost_estimate_usd = 0.0
            job.entity_count = 0
            job.relation_count = 0

            try:
                await _cleanup_document_artifacts(db, document_id)

                job.started_parsing_at = datetime.utcnow()
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
                job.completed_parsing_at = datetime.utcnow()
                logger.info("[ingestion] Extracted %s characters of text from document_id=%s", len(text), document_id)
                if not text:
                    raise ValueError("No extractable text found in document")

                job.started_chunking_at = datetime.utcnow()
                await _set_document_status(db, doc, STATUS_CHUNKING, job=job)
                logger.info("[ingestion] Chunking text for document_id=%s", document_id)
                chunks = chunk_text(text)
                chunk_texts = [span.text for span in chunks]
                job.chunk_count = len(chunks)
                job.completed_chunking_at = datetime.utcnow()
                logger.info("[ingestion] Generated %s chunks for document_id=%s", len(chunks), document_id)
                if not chunks:
                    raise ValueError("Document text did not produce any chunks")

                # Contextual retrieval: antepone titolo/categoria/descrizione, sezione (se rilevata) e,
                # se abilitato, un contesto situazionale generato da LLM (vedi contextual_chunking.py)
                # al testo di ogni chunk solo per l'embedding e il vettore sparso. Il testo salvato per
                # citazioni e contesto LLM di risposta (chunk_text_content) resta quello originale.
                document_context = _build_document_context(filename, doc.category, doc.description)
                section_titles = [_infer_section_title(chunk_text) for chunk_text in chunk_texts]

                llm_contexts: list[str] = ["" for _ in chunks]
                if settings.enable_rich_contextual_retrieval:
                    logger.info(
                        "[ingestion] Generazione contesto LLM per %s chunk di document_id=%s", len(chunks), document_id
                    )
                    llm_contexts = await generate_chunk_contexts(text, chunk_texts)
                    ctx_input_tokens = _count_tokens_for_model(chunk_texts, settings.contextual_retrieval_model)
                    ctx_output_tokens = _count_tokens_for_model(llm_contexts, settings.contextual_retrieval_model)
                    job.input_tokens = (job.input_tokens or 0) + ctx_input_tokens
                    job.output_tokens = (job.output_tokens or 0) + ctx_output_tokens
                    job.cost_estimate_usd = (job.cost_estimate_usd or 0.0) + estimate_cost_usd(
                        settings.contextual_retrieval_model, ctx_input_tokens, ctx_output_tokens
                    )

                job.started_embedding_at = datetime.utcnow()
                embedding_inputs = [
                    _build_chunk_embedding_input(document_context, section_title, chunk_text, llm_context)
                    for chunk_text, section_title, llm_context in zip(chunk_texts, section_titles, llm_contexts)
                ]

                # BM25 globale: registra i termini di questo documento nel vocabolario condiviso
                # (Postgres + cache Redis) e fotografa le statistiche del corpus *esistente* (df/N
                # di tutti gli altri documenti già indicizzati) prima di aggiungere questo documento.
                # Vedi sparse_corpus_stats.py: l'IDF/lunghezza media sono calcolate sull'intero KB,
                # non solo sui chunk di questo documento.
                per_chunk_tokens = [tokenize_sparse(chunk) for chunk in embedding_inputs]
                all_terms = {term for tokens in per_chunk_tokens for term in tokens}
                term_id_map = await get_or_create_term_ids(db, all_terms)
                global_df, total_chunks_before, avg_doc_len = get_global_stats_snapshot(term_id_map.values())
                logger.debug(
                    "[ingestion] Vocabolario BM25: %s termini in questo documento, corpus esistente: %s chunk",
                    len(term_id_map),
                    total_chunks_before,
                )

                # Embed chunks
                await _set_document_status(db, doc, STATUS_EMBEDDING, job=job)
                logger.info("[ingestion] Generating embeddings for %s chunks of document_id=%s", len(chunks), document_id)
                embeddings = await embed_texts(embedding_inputs)
                emb_input_tokens = _count_tokens_for_model(embedding_inputs, settings.embedding_model)
                job.input_tokens = (job.input_tokens or 0) + emb_input_tokens
                job.cost_estimate_usd = (job.cost_estimate_usd or 0.0) + estimate_cost_usd(
                    settings.embedding_model, emb_input_tokens, 0
                )
                job.completed_embedding_at = datetime.utcnow()
                logger.info("[ingestion] Embeddings generated for document_id=%s", document_id)
                if len(embeddings) != len(chunks):
                    raise ValueError(f"Embedding count mismatch: chunks={len(chunks)} embeddings={len(embeddings)}")

                qdrant_points = []
                chunk_records = []
                for idx, (chunk_text_content, embedding, section_title, embedding_input, chunk_tokens, chunk_span) in enumerate(
                    zip(chunk_texts, embeddings, section_titles, embedding_inputs, per_chunk_tokens, chunks)
                ):
                    text_hash = _hash_text(chunk_text_content)
                    token_count = _token_count(chunk_text_content, settings.embedding_model)
                    # Span dal chunker (offset-tracking): text[span.start:span.end] == chunk_text_content,
                    # quindi le citazioni sono verificabili e allineate alle pagine (vedi chunking.ChunkSpan).
                    span_start, span_end = chunk_span.start, chunk_span.end
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
                                weighted_sparse_vector(chunk_tokens, term_id_map, global_df, total_chunks_before, avg_doc_len),
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
                    job.started_vector_indexing_at = datetime.utcnow()
                    await _set_document_status(db, doc, STATUS_VECTOR_INDEXING, job=job)
                    logger.info("[ingestion] Upserting %s vectors to Qdrant for document_id=%s", len(qdrant_points), document_id)
                    vector_store.upsert(qdrant_points)
                    job.completed_vector_indexing_at = datetime.utcnow()
                    logger.info("[ingestion] Vectors upserted for document_id=%s", document_id)

                # Pubblica il contributo BM25 di questo documento alle statistiche globali (df/N
                # condivise da tutti i documenti, usate anche a query-time per l'IDF). La vecchia
                # versione era già stata sottratta in _cleanup_document_artifacts in caso di reindex.
                doc_term_counts: dict[str, int] = {}
                for tokens in per_chunk_tokens:
                    for term in set(tokens):
                        doc_term_counts[term] = doc_term_counts.get(term, 0) + 1
                doc_total_tokens = sum(len(tokens) for tokens in per_chunk_tokens)
                doc.sparse_term_counts = doc_term_counts
                doc.sparse_total_tokens = doc_total_tokens
                await db.commit()
                positive_counts = {term_id_map[term]: count for term, count in doc_term_counts.items()}
                apply_document_delta(positive_counts, len(chunks), doc_total_tokens)
                logger.info(
                    "[ingestion] Statistiche BM25 globali aggiornate per document_id=%s (%s termini unici, %s chunk)",
                    document_id,
                    len(doc_term_counts),
                    len(chunks),
                )

                job.started_graph_indexing_at = datetime.utcnow()
                await _set_document_status(db, doc, STATUS_GRAPH_INDEXING, job=job)
                logger.info("[ingestion] Adding document node to graph: document_id=%s", document_id)
                graph_store.add_document(document_id, filename, content_type, user_id=user_id)
                logger.info("[ingestion] Document node added to graph: document_id=%s", document_id)

                progress_step = max(1, len(chunks) // 20)
                # GLiNER ed estrazione relazioni LLM girano su TUTTI i chunk: niente cap per costo,
                # altrimenti la maggior parte delle entità di documenti lunghi resta isolata nel grafo.

                for idx, chunk_text_content in enumerate(chunks):
                    text_hash = _hash_text(chunk_text_content)
                    chunk_id = _stable_uuid("chunk", document_id, idx, text_hash)

                    logger.debug("[ingestion] Adding chunk %s/%s to graph for document_id=%s", idx + 1, len(chunks), document_id)
                    graph_store.add_chunk(chunk_id, document_id, chunk_text_content, idx, user_id=user_id)

                    # 1. Estrazione entità con GLiNER su TUTTI i chunk.
                    logger.debug("[ingestion] Extracting entities with GLiNER for chunk %s/%s of document_id=%s", idx + 1, len(chunks), document_id)
                    try:
                        entities = gliner_extract_entities(chunk_text_content)
                    except Exception as extraction_error:
                        logger.warning(
                            "[ingestion] GLiNER entity extraction failed for chunk %s/%s of document_id=%s: %s",
                            idx + 1,
                            len(chunks),
                            document_id,
                            extraction_error,
                        )
                        entities = []

                    # 2. Estrazione relazioni con LLM per ogni chunk (extract_relations salta da sé
                    # i chunk con meno di 2 entità, quindi qui non serve un cap manuale).
                    logger.debug("[ingestion] Extracting relations with LLM for chunk %s/%s of document_id=%s", idx + 1, len(chunks), document_id)
                    try:
                        relations = await extract_relations(chunk_text_content, entities)
                    except Exception as extraction_error:
                        logger.warning(
                            "[ingestion] Relation extraction failed for chunk %s/%s of document_id=%s: %s",
                            idx + 1,
                            len(chunks),
                            document_id,
                            extraction_error,
                        )
                        relations = []

                    logger.debug(
                        "[ingestion] Chunk %s/%s extracted %s entities and %s relations for document_id=%s",
                        idx + 1,
                        len(chunks),
                        len(entities),
                        len(relations),
                        document_id,
                    )
                    job.entity_count = (job.entity_count or 0) + len(entities)
                    job.relation_count = (job.relation_count or 0) + len(relations)

                    rel_input_tokens = _token_count(chunk_text_content, settings.openai_model)
                    rel_output_tokens = _count_tokens_for_model([str(r) for r in relations], settings.openai_model)
                    job.input_tokens = (job.input_tokens or 0) + rel_input_tokens
                    job.output_tokens = (job.output_tokens or 0) + rel_output_tokens
                    job.cost_estimate_usd = (job.cost_estimate_usd or 0.0) + estimate_cost_usd(
                        settings.openai_model, rel_input_tokens, rel_output_tokens
                    )

                    graph_store.add_entities_and_relations(chunk_id, entities, relations)
                    if (idx + 1) % progress_step == 0 or idx + 1 == len(chunks):
                        graph_progress = 80 + int(((idx + 1) / len(chunks)) * 18)
                        await _set_document_status(db, doc, STATUS_GRAPH_INDEXING, job=job, progress=graph_progress)

                job.completed_graph_indexing_at = datetime.utcnow()
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
