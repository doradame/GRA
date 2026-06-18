import logging
from celery import Celery
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

celery_app = Celery(
    "graph_rag_assistant",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks.ingestion", "app.tasks.entity_resolution"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour hard limit
    task_soft_time_limit=3300,  # 55 min soft limit
    worker_prefetch_multiplier=1,
    worker_send_task_events=True,
    task_send_sent_event=True,
)

logger.info(
    "Celery configured with broker=%s backend=%s",
    settings.celery_broker_url,
    settings.celery_result_backend,
)
