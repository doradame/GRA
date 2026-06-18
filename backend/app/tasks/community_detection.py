import asyncio
import logging

from celery import shared_task

from app.services.community_detection import run_community_detection

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def community_detection_task(self, algorithm: str = "louvain", resolution: float = 1.0):
    logger.info("[community_detection_task] Avvio: algorithm=%s resolution=%s", algorithm, resolution)
    try:
        result = asyncio.run(run_community_detection(algorithm=algorithm, resolution=resolution))
        return result
    except Exception as exc:
        logger.exception("[community_detection_task] Fallito")
        raise self.retry(exc=exc, countdown=60)
