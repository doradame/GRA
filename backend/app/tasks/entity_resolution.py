import asyncio
import logging

from celery import shared_task

from app.services.entity_resolution import resolve_entities

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def resolve_entities_task(self, threshold: float = 0.93):
    """Celery task per la entity resolution fuzzy sul grafo Neo4j."""
    logger.info(
        "[celery] Entity resolution task %s started (threshold=%s, retry=%s)",
        self.request.id,
        threshold,
        self.request.retries,
    )
    try:
        result = asyncio.run(resolve_entities(threshold=threshold))
        logger.info("[celery] Entity resolution task %s completed: %s", self.request.id, result)
        return result
    except Exception as exc:
        logger.exception("[celery] Entity resolution task %s failed: %s", self.request.id, exc)
        raise self.retry(exc=exc, countdown=120)
