import asyncio
import logging

from celery import shared_task

from app.core.locks import acquire_lock, release_lock, DEFAULT_LOCK_TTL_SECONDS
from app.services.community_detection import run_community_detection

logger = logging.getLogger(__name__)

# Chiave del lock distribuito condivisa tra questo task e il check soft nel router.
LOCK_KEY = "lock:job:community_detection"


@shared_task(bind=True, max_retries=0)
def community_detection_task(self, algorithm: str = "louvain", resolution: float = 1.0):
    """Celery task per la community detection sul grafo.

    Guardato da un lock distribuito: rebuild concorrenti corromperebbero i
    CommunitySummary, quindi un secondo run mentre uno è in corso viene saltato.
    Nessun retry automatico: il rebuild è parzialmente distruttivo, l'admin lo
    ri-triggera manualmente in caso di fallimento.
    """
    token = self.request.id
    if not acquire_lock(LOCK_KEY, token, DEFAULT_LOCK_TTL_SECONDS):
        logger.warning(
            "[community_detection_task] Task %s skipped: un altro run è in corso",
            self.request.id,
        )
        return {"status": "skipped", "reason": "already_running", "task_id": self.request.id}
    logger.info(
        "[community_detection_task] Avvio: algorithm=%s resolution=%s", algorithm, resolution
    )
    try:
        result = asyncio.run(run_community_detection(algorithm=algorithm, resolution=resolution))
        return result
    finally:
        release_lock(LOCK_KEY, token)
