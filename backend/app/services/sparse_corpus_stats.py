import logging
from typing import Dict, Iterable

import redis
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.models import Chunk, Document, SparseTerm

settings = get_settings()
logger = logging.getLogger(__name__)

REDIS_VOCAB_KEY = "bm25:vocab"
REDIS_DF_KEY = "bm25:df"
REDIS_TOTAL_CHUNKS_KEY = "bm25:total_chunks"
REDIS_TOTAL_TOKENS_KEY = "bm25:total_tokens"

_redis_client = None


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(settings.celery_broker_url, decode_responses=True)
    return _redis_client


async def get_or_create_term_ids(db: AsyncSession, terms: Iterable[str]) -> Dict[str, int]:
    """Mappa stabile term -> id intero, persistita in Postgres (tabella sparse_terms) e
    rispecchiata nella cache Redis (per le lookup a query-time, che non hanno una sessione DB).

    Gli id non vengono mai riassegnati: una volta creato, un id resta valido per sempre,
    perché i vettori sparsi già scritti su Qdrant lo referenziano come indice.
    """
    unique_terms = sorted(set(terms))
    if not unique_terms:
        return {}

    result = await db.execute(select(SparseTerm).where(SparseTerm.term.in_(unique_terms)))
    mapping = {row.term: row.id for row in result.scalars().all()}

    missing = [t for t in unique_terms if t not in mapping]
    if missing:
        stmt = pg_insert(SparseTerm).values([{"term": t} for t in missing]).on_conflict_do_nothing(index_elements=["term"])
        await db.execute(stmt)
        await db.commit()
        result = await db.execute(select(SparseTerm).where(SparseTerm.term.in_(missing)))
        newly_created = {row.term: row.id for row in result.scalars().all()}
        mapping.update(newly_created)
        _cache_vocab(newly_created)

    return mapping


def _cache_vocab(term_ids: Dict[str, int]) -> None:
    if not term_ids:
        return
    try:
        r = _get_redis()
        r.hset(REDIS_VOCAB_KEY, mapping={term: str(tid) for term, tid in term_ids.items()})
    except Exception as exc:
        logger.warning("[sparse_corpus_stats] Aggiornamento cache vocabolario fallito: %s", exc)


def get_term_ids_cached(terms: Iterable[str]) -> Dict[str, int]:
    """Lookup a sola lettura del vocabolario dalla cache Redis (usato a query-time, dove non
    è disponibile una sessione DB async). I termini non ancora visti in indexing vengono
    semplicemente omessi: non possono comunque corrispondere a nessun chunk indicizzato."""
    unique_terms = sorted(set(terms))
    if not unique_terms:
        return {}
    try:
        r = _get_redis()
        values = r.hmget(REDIS_VOCAB_KEY, unique_terms)
        return {term: int(v) for term, v in zip(unique_terms, values) if v is not None}
    except Exception as exc:
        logger.warning("[sparse_corpus_stats] Lettura cache vocabolario fallita: %s", exc)
        return {}


def get_global_stats_snapshot(term_ids: Iterable[int]) -> tuple[Dict[int, int], int, float]:
    """Ritorna (document_frequency per term_id, numero totale di chunk, lunghezza media chunk)
    per l'intero corpus indicizzato finora.

    Usato sia in indexing (IDF/lunghezza media dei termini del documento corrente rispetto al
    corpus *esistente*, prima che questo documento venga aggiunto) sia in query-time (IDF dei
    termini della query rispetto a tutto il corpus).
    """
    term_ids = list(term_ids)
    total_chunks = _get_int(REDIS_TOTAL_CHUNKS_KEY)
    total_tokens = _get_int(REDIS_TOTAL_TOKENS_KEY)
    avg_doc_len = (total_tokens / total_chunks) if total_chunks > 0 else 1.0

    if not term_ids:
        return {}, total_chunks, avg_doc_len
    try:
        r = _get_redis()
        values = r.hmget(REDIS_DF_KEY, [str(tid) for tid in term_ids])
        df = {tid: int(v) for tid, v in zip(term_ids, values) if v is not None}
        return df, total_chunks, avg_doc_len
    except Exception as exc:
        logger.warning("[sparse_corpus_stats] Lettura statistiche globali fallita: %s", exc)
        return {}, total_chunks, avg_doc_len


def _get_int(key: str) -> int:
    try:
        r = _get_redis()
        return int(r.get(key) or 0)
    except Exception as exc:
        logger.warning("[sparse_corpus_stats] Lettura contatore %s fallita: %s", key, exc)
        return 0


def apply_document_delta(term_id_counts: Dict[int, int], chunk_count_delta: int, token_count_delta: int) -> None:
    """Applica in modo atomico il contributo (positivo o negativo) di un documento alle
    statistiche BM25 globali in Redis. Usare con segno negativo su delete/reindex per
    sottrarre il contributo precedente prima di aggiungere quello nuovo."""
    if not term_id_counts and not chunk_count_delta and not token_count_delta:
        return
    try:
        r = _get_redis()
        pipe = r.pipeline()
        for term_id, count in term_id_counts.items():
            if count:
                pipe.hincrby(REDIS_DF_KEY, str(term_id), count)
        if chunk_count_delta:
            pipe.incrby(REDIS_TOTAL_CHUNKS_KEY, chunk_count_delta)
        if token_count_delta:
            pipe.incrby(REDIS_TOTAL_TOKENS_KEY, token_count_delta)
        pipe.execute()
    except Exception as exc:
        logger.warning("[sparse_corpus_stats] Aggiornamento statistiche globali fallito: %s", exc)


async def subtract_document_contribution(db: AsyncSession, document_id: str) -> None:
    """Sottrae dalle statistiche BM25 globali il contributo di un documento (in vista di
    eliminazione o reindex) e azzera le colonne sparse_term_counts/sparse_total_tokens.

    Va chiamata PRIMA di eliminare effettivamente i Chunk del documento (serve contarli).
    """
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc or not doc.sparse_term_counts:
        return

    chunk_count_result = await db.execute(select(func.count(Chunk.id)).where(Chunk.document_id == document_id))
    chunk_count = chunk_count_result.scalar() or 0

    term_ids = await get_or_create_term_ids(db, doc.sparse_term_counts.keys())
    negative_counts = {
        term_ids[term]: -count for term, count in doc.sparse_term_counts.items() if term in term_ids
    }
    apply_document_delta(negative_counts, -chunk_count, -(doc.sparse_total_tokens or 0))
    doc.sparse_term_counts = None
    doc.sparse_total_tokens = None


def reset_global_stats() -> None:
    """Azzera completamente le statistiche BM25 globali in Redis (usato dal reset della KB)."""
    try:
        r = _get_redis()
        r.delete(REDIS_VOCAB_KEY, REDIS_DF_KEY, REDIS_TOTAL_CHUNKS_KEY, REDIS_TOTAL_TOKENS_KEY)
        logger.info("[sparse_corpus_stats] Statistiche globali azzerate (reset KB)")
    except Exception as exc:
        logger.warning("[sparse_corpus_stats] Reset statistiche globali fallito: %s", exc)


async def recompute_global_stats_from_postgres(db: AsyncSession) -> None:
    """Ricostruisce da zero le statistiche globali in Redis a partire da Postgres (fonte di
    verità: Document.sparse_term_counts/sparse_total_tokens, già calcolati una volta in
    indexing, più il conteggio reale dei chunk).

    Utility di recovery: utile se Redis viene svuotato o se si sospetta una deriva tra le
    statistiche cache e i dati persistiti.
    """
    result = await db.execute(
        select(Document.sparse_term_counts, Document.sparse_total_tokens).where(
            Document.sparse_term_counts.isnot(None)
        )
    )
    aggregated: Dict[str, int] = {}
    total_tokens = 0
    for term_counts, doc_tokens in result.all():
        if term_counts:
            for term, count in term_counts.items():
                aggregated[term] = aggregated.get(term, 0) + count
        if doc_tokens:
            total_tokens += doc_tokens

    term_ids = await get_or_create_term_ids(db, aggregated.keys())

    all_terms_result = await db.execute(select(SparseTerm.term, SparseTerm.id))
    full_vocab = {term: tid for term, tid in all_terms_result.all()}

    total_chunks_result = await db.execute(select(func.count(Chunk.id)))
    total_chunks = total_chunks_result.scalar() or 0

    try:
        r = _get_redis()
        pipe = r.pipeline()
        pipe.delete(REDIS_DF_KEY)
        pipe.delete(REDIS_VOCAB_KEY)
        if full_vocab:
            pipe.hset(REDIS_VOCAB_KEY, mapping={term: str(tid) for term, tid in full_vocab.items()})
        for term, count in aggregated.items():
            term_id = term_ids.get(term)
            if term_id is not None:
                pipe.hset(REDIS_DF_KEY, str(term_id), count)
        pipe.set(REDIS_TOTAL_CHUNKS_KEY, total_chunks)
        pipe.set(REDIS_TOTAL_TOKENS_KEY, total_tokens)
        pipe.execute()
        logger.info(
            "[sparse_corpus_stats] Statistiche globali ricostruite: %s termini, %s chunk, %s token totali",
            len(aggregated),
            total_chunks,
            total_tokens,
        )
    except Exception as exc:
        logger.warning("[sparse_corpus_stats] Ricostruzione statistiche globali fallita: %s", exc)
