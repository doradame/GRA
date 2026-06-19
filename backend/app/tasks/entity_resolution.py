import asyncio
import logging

from celery import shared_task

from app.core.locks import acquire_lock, release_lock, DEFAULT_LOCK_TTL_SECONDS
from app.services.entity_resolution import resolve_entities

logger = logging.getLogger(__name__)

# Chiave del lock distribuito condivisa tra questo task e il check soft nel router.
LOCK_KEY = "lock:job:entity_resolution"


@shared_task(bind=True, max_retries=0)
def resolve_entities_task(self, threshold: float = 0.93):
    """Celery task per la entity resolution fuzzy sul grafo Neo4j.

    Guardato da un lock distribuito: se un altro run è già in corso il task viene
    saltato (skip) invece che eseguito in parallelo — il merge di entità non è sicuro
    sotto run concorrenti. Nessun retry automatico: l'operazione è parzialmente
    mutante, in caso di fallimento l'admin la ri-triggera manualmente.
    """
    token = self.request.id
    if not acquire_lock(LOCK_KEY, token, DEFAULT_LOCK_TTL_SECONDS):
        logger.warning(
            "[celery] Entity resolution task %s skipped: un altro run è in corso",
            self.request.id,
        )
        return {"status": "skipped", "reason": "already_running", "task_id": self.request.id}
    logger.info(
        "[celery] Entity resolution task %s started (threshold=%s)",
        self.request.id,
        threshold,
    )
    try:
        result = asyncio.run(resolve_entities(threshold=threshold))
        logger.info("[celery] Entity resolution task %s completed: %s", self.request.id, result)
        return result
    finally:
        release_lock(LOCK_KEY, token)
