import logging
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func

from app.core.database import get_db
from app.core.auth import get_current_user, get_current_active_admin
from app.models.models import User, Document, Chunk, IngestionJob
from app.models.schemas import DocumentOut, DocumentList, IngestionJobList
from app.services.ingestion import SCHEDULABLE_STATUSES, create_document
from app.tasks.ingestion import ingest_document_task
from app.services.storage import storage
from app.services.vector_store import vector_store
from app.services.graph_store import graph_store
from app.services.api_usage import reset_api_usage

router = APIRouter()
logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 100 * 1024 * 1024
SUPPORTED_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "text/plain",
    "text/markdown",
    "text/csv",
    "text/html",
    "application/json",
}


@router.post("/upload", response_model=DocumentOut)
async def upload_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not file.content_type:
        logger.warning("[upload] Rejected upload with unknown content type")
        raise HTTPException(status_code=400, detail="Unknown content type")
    if file.content_type not in SUPPORTED_CONTENT_TYPES and not file.content_type.startswith("text/"):
        logger.warning("[upload] Rejected unsupported content type: %s", file.content_type)
        raise HTTPException(status_code=415, detail=f"Unsupported content type: {file.content_type}")

    data = await file.read()
    if len(data) == 0:
        logger.warning("[upload] Rejected empty file upload")
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        logger.warning("[upload] Rejected oversized upload: size=%s", len(data))
        raise HTTPException(status_code=413, detail="File too large")

    logger.info(
        "[upload] User %s uploading file=%s content_type=%s size=%s",
        current_user.id,
        file.filename,
        file.content_type,
        len(data),
    )

    try:
        doc = await create_document(
            db=db,
            filename=file.filename or "unnamed",
            content_type=file.content_type,
            data=data,
            user_id=str(current_user.id),
        )
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.exception("[upload] Failed to create document record: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

    # New uploads and failed duplicates are schedulable; completed duplicates are returned as-is.
    if doc.status in SCHEDULABLE_STATUSES:
        logger.info(
            "[upload] Scheduling Celery task for document_id=%s user=%s",
            doc.id,
            current_user.id,
        )
        ingest_document_task.delay(
            document_id=str(doc.id),
            filename=doc.filename,
            content_type=doc.content_type,
            storage_key=doc.storage_key,
            user_id=str(current_user.id),
        )
        logger.info("[upload] Celery task scheduled for document_id=%s", doc.id)
    else:
        logger.info(
            "[upload] Document %s returned without scheduling (status=%s)",
            doc.id,
            doc.status,
        )

    return doc


@router.get("/", response_model=DocumentList)
async def list_documents(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    logger.debug("[documents] Listing documents for user=%s skip=%s limit=%s", current_user.id, skip, limit)
    result = await db.execute(
        select(Document)
        .where(Document.created_by == current_user.id)
        .order_by(desc(Document.created_at))
        .offset(skip)
        .limit(limit)
    )
    items = result.scalars().all()
    count_result = await db.execute(
        select(func.count(Document.id)).where(Document.created_by == current_user.id)
    )
    total = count_result.scalar() or 0
    logger.debug("[documents] Found %s documents", total)
    return DocumentList(items=items, total=total)


@router.get("/jobs/recent", response_model=IngestionJobList)
async def list_recent_ingestion_jobs(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    safe_limit = min(max(limit, 1), 200)
    result = await db.execute(
        select(IngestionJob)
        .join(Document, IngestionJob.document_id == Document.id)
        .where(Document.created_by == current_user.id)
        .order_by(desc(IngestionJob.created_at))
        .limit(safe_limit)
    )
    jobs = result.scalars().all()
    return IngestionJobList(items=jobs, total=len(jobs))


@router.get("/{document_id}/jobs", response_model=IngestionJobList)
async def list_document_ingestion_jobs(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.created_by == current_user.id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    jobs_result = await db.execute(
        select(IngestionJob)
        .where(IngestionJob.document_id == document_id)
        .order_by(desc(IngestionJob.created_at))
    )
    jobs = jobs_result.scalars().all()
    return IngestionJobList(items=jobs, total=len(jobs))


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    logger.debug("[documents] Fetching document_id=%s", document_id)
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.created_by == current_user.id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        logger.warning("[documents] Document not found: %s", document_id)
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.post("/{document_id}/reindex", response_model=DocumentOut)
async def reindex_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    logger.info("[documents] Reindex requested for document_id=%s by user=%s", document_id, current_user.id)
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.created_by == current_user.id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    doc.status = "uploaded"
    doc.error_message = None
    await db.commit()
    await db.refresh(doc)

    ingest_document_task.delay(
        document_id=str(doc.id),
        filename=doc.filename,
        content_type=doc.content_type,
        storage_key=doc.storage_key,
        user_id=str(current_user.id),
    )
    return doc


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    logger.info("[documents] Deleting document_id=%s by user=%s", document_id, current_user.id)
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.created_by == current_user.id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        logger.warning("[documents] Delete failed: document not found %s", document_id)
        raise HTTPException(status_code=404, detail="Document not found")

    # Delete from graph, vector store, object storage and database
    logger.info("[documents] Removing graph data for document_id=%s", document_id)
    graph_store.delete_document(document_id)
    logger.info("[documents] Removing vectors for document_id=%s", document_id)
    vector_store.delete_by_document(document_id)
    logger.info("[documents] Removing object storage file %s", doc.storage_key)
    storage.delete(doc.storage_key)
    await db.delete(doc)
    await db.commit()
    logger.info("[documents] Deleted document_id=%s", document_id)
    return None


@router.post("/reset", status_code=status.HTTP_200_OK)
async def reset_knowledge_base(
    confirm: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_admin),
):
    logger.info("[documents] Reset requested by admin=%s confirm=%s", current_user.id, confirm)
    if not confirm:
        logger.warning("[documents] Reset rejected: confirm=false")
        raise HTTPException(status_code=400, detail="Pass confirm=true to reset the knowledge base")

    # Reset graph
    logger.info("[documents] Resetting graph store")
    graph_store.reset()

    # Reset vector store
    logger.info("[documents] Resetting vector store")
    vector_store.reset_collection()

    # Reset API usage counters
    logger.info("[documents] Resetting API usage counters")
    reset_api_usage()

    # Delete all documents from object storage and database
    result = await db.execute(select(Document))
    docs = result.scalars().all()
    logger.info("[documents] Removing %s documents from storage and database", len(docs))
    for doc in docs:
        try:
            storage.delete(doc.storage_key)
        except Exception:
            pass
        await db.delete(doc)
    await db.commit()
    logger.info("[documents] Knowledge base reset completed by admin=%s", current_user.id)
    return {"detail": "Knowledge base reset successfully"}
