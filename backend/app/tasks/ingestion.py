import logging
import asyncio
from celery import shared_task

from app.services.ingestion import process_document

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def ingest_document_task(self, document_id: str, filename: str, content_type: str, storage_key: str, user_id: str):
    """Celery task wrapper for the async ingestion pipeline."""
    logger.info(
        "[celery] Task %s received for document_id=%s filename=%s",
        self.request.id,
        document_id,
        filename,
    )
    try:
        asyncio.run(
            process_document(
                document_id,
                filename,
                content_type,
                storage_key,
                user_id,
                task_id=self.request.id,
                retry_count=self.request.retries,
            )
        )
        logger.info("[celery] Task %s completed for document_id=%s", self.request.id, document_id)
    except Exception as exc:
        logger.exception(
            "[celery] Task %s failed for document_id=%s: %s",
            self.request.id,
            document_id,
            exc,
        )
        # Let Celery retry the task.
        raise self.retry(exc=exc, countdown=60)
