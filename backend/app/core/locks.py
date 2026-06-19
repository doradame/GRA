"""Lock distribuito basato su Redis per impedire run concorrenti di job admin.

Usato dai task Celery di entity resolution e community detection: un job che non
riuscisse ad acquisire il lock viene saltato (skip) invece che eseguito in parallelo
con un run precedente — il merge di entità e il rebuild dei CommunitySummary non
sono sicuri sotto run concorrenti.

Il rilascio usa uno script Lua compare-and-set, così non si cancella mai il lock di
un altro detentore (es. se il nostro lock è scaduto per TTL e nel frattempo è stato
riacquisito con un token diverso).

Pulizia dei lock orfani: il worker gira con acks_late=False (default), quindi un
worker killato non requeue il task e non rilascia il lock pulitamente. L'unico
backstop in quel caso è lo scadere del TTL — per questo DEFAULT_LOCK_TTL_SECONDS è
>= del task_time_limit (hard limit 3600s). Un lock orfano si libera al massimo dopo
TTL secondi di "falso occupato".
"""
import logging
from typing import Optional

import redis

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Rilascia il lock solo se il token corrisponde (compare-and-set). Evita di
# cancellare un lock che nel frattempo è scaduto ed è stato riacquisito da altri.
_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""

# TTL di default: hard time limit Celery (3600s) + margine di sicurezza. Vedi modulo
# docstring per la scelta del valore rispetto al cleanup dei lock orfani.
DEFAULT_LOCK_TTL_SECONDS = 4200

_redis_client: Optional[redis.Redis] = None


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(
            get_settings().celery_broker_url, decode_responses=True
        )
    return _redis_client


def acquire_lock(key: str, token: str, ttl: int = DEFAULT_LOCK_TTL_SECONDS) -> bool:
    """Tenta di acquisire `key` con il `token` dato, scadenza `ttl` secondi.

    Ritorna True se acquisito, False se era già detenuto da altri. Atomico via SET NX EX.
    """
    acquired = _get_redis().set(key, token, nx=True, ex=ttl)
    if acquired:
        logger.debug("Lock %s acquisito (token=%s, ttl=%ss)", key, token, ttl)
    return bool(acquired)


def release_lock(key: str, token: str) -> None:
    """Rilascia il lock solo se il token corrisponde (CAS via Lua). No-op altrimenti."""
    try:
        _get_redis().eval(_RELEASE_SCRIPT, 1, key, token)
    except redis.RedisError:
        logger.warning("Impossibile rilasciare il lock %s (token=%s)", key, token, exc_info=True)


def is_locked(key: str) -> bool:
    """Check soft, non autoritativo: True se la chiave di lock esiste attualmente.

    Usato dai router per dare feedback immediato (409) all'admin. La vera barriera
    contro run concorrenti resta acquire_lock() dentro il task: c'è una race tra questo
    check e l'avvio del task che il guard nel task copre.
    """
    try:
        return bool(_get_redis().exists(key))
    except redis.RedisError:
        # Se Redis non risponde, non blocchiamo il trigger: il guard nel task deciderà.
        return False
