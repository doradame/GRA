import json
import logging
from typing import List, Optional
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    Fusion,
    FusionQuery,
    NamedSparseVector,
    NamedVector,
    PointStruct,
    Prefetch,
    SparseVector,
    SparseVectorParams,
    Filter,
    FieldCondition,
    MatchValue,
    VectorParams,
    PayloadSchemaType,
)
from app.core.config import get_settings
from app.core.retry import retry_sync

settings = get_settings()
logger = logging.getLogger(__name__)

VECTOR_SIZE = settings.embedding_dimensions

# Ogni float di un dense vector occupa ~14 byte una volta serializzato in JSON (segno,
# cifre, virgola). Stimare cosi (senza serializzare l'intero vector) basta per il
# batching size-aware verso Qdrant; la stima tende a sovrastimare leggermente, il che e'
# sicuro (sottostimare significherebbe ribattere nel limite 32 MiB di Qdrant).
_JSON_FLOAT_BYTES = 14


def _estimate_point_size(point: PointStruct) -> int:
    """Stima approssimata dei byte del JSON di un PointStruct, per il batching size-aware.

    Include dense vector, sparse vector (BM25 nativo) e payload. Il payload (testo del
    chunk) viene serializzato per misurarne la dimensione reale; i vettori sono stimati
    a partire dal numero di elementi. Conservativa: meglio flushare un batch prima.
    """
    size = (
        len(json.dumps(point.payload, default=str).encode("utf-8"))
        if point.payload
        else 0
    )

    vector = point.vector
    if isinstance(vector, dict):
        for value in vector.values():
            if isinstance(value, SparseVector):
                # indici (int) + valori (float) della sparse BM25
                size += len(value.indices) * 8 + len(value.values) * _JSON_FLOAT_BYTES
            elif isinstance(value, (list, tuple)):
                size += len(value) * _JSON_FLOAT_BYTES
    elif isinstance(vector, (list, tuple)):
        size += len(vector) * _JSON_FLOAT_BYTES

    return size + 128  # envelope per point (id, field name, parentesi)


class VectorStore:
    def __init__(self):
        self._client = None
        self.collection = settings.qdrant_collection

    @property
    def client(self):
        if self._client is None:
            logger.info("[vector] Initializing Qdrant client: %s", settings.qdrant_url)
            self._client = QdrantClient(url=settings.qdrant_url)
            self._ensure_collection()
            logger.info("[vector] Qdrant client ready")
        return self._client

    def _ensure_collection(self):
        collections = self._client.get_collections().collections
        names = [c.name for c in collections]
        if self.collection not in names:
            logger.info("[vector] Creating Qdrant collection: %s", self.collection)
            if settings.qdrant_enable_native_sparse:
                self._client.create_collection(
                    collection_name=self.collection,
                    vectors_config={
                        settings.qdrant_dense_vector_name: VectorParams(
                            size=VECTOR_SIZE,
                            distance=Distance.COSINE,
                        )
                    },
                    sparse_vectors_config={
                        settings.qdrant_sparse_vector_name: SparseVectorParams()
                    },
                )
            else:
                self._client.create_collection(
                    collection_name=self.collection,
                    vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
                )
        else:
            if settings.qdrant_enable_native_sparse:
                self._warn_if_sparse_collection_missing()
            logger.debug("[vector] Qdrant collection already exists: %s", self.collection)

        # Indici sui campi filtrati a query-time (user_id, document_id): senza di questi i
        # filtri multi-tenant sono full-scan sulle collection grandi.
        self._ensure_payload_indexes()

    def _warn_if_sparse_collection_missing(self):
        info = self._client.get_collection(self.collection)
        sparse_vectors = getattr(getattr(info, "config", None), "params", None)
        sparse_vectors = getattr(sparse_vectors, "sparse_vectors", None)
        if not sparse_vectors or settings.qdrant_sparse_vector_name not in sparse_vectors:
            logger.warning(
                "[vector] QDRANT_ENABLE_NATIVE_SPARSE=true but collection %s has no sparse vector '%s'. "
                "Reset/recreate the collection and reindex documents.",
                self.collection,
                settings.qdrant_sparse_vector_name,
            )

    def _ensure_payload_indexes(self):
        """Crea indici di payload su user_id/document_id se mancanti (filtri query-time).

        Idempotente: legge lo schema esistente e crea solo i campi non ancora indicizzati,
        cosi funziona sia su collection nuove sia gia esistenti. Fallimenti (es. versione
        Qdrant senza payload index) sono warn-only: l'indice e un'ottimizzazione, non un
        requisito di correttezza.
        """
        try:
            info = self._client.get_collection(self.collection)
            existing = set((info.payload_schema or {}).keys())
        except Exception as exc:
            logger.warning("[vector] Cannot read payload schema for index check: %s", exc)
            return
        for field in ("user_id", "document_id"):
            if field in existing:
                continue
            try:
                self._client.create_payload_index(
                    collection_name=self.collection,
                    field_name=field,
                    field_schema=PayloadSchemaType.KEYWORD,
                )
                logger.info("[vector] Created payload index on %s.%s", self.collection, field)
            except Exception as exc:
                logger.warning("[vector] Could not create payload index on %s: %s", field, exc)

    def upsert(self, points: List[PointStruct], batch_size: Optional[int] = None):
        if batch_size is None:
            batch_size = settings.qdrant_upsert_batch_size
        max_bytes = settings.qdrant_max_request_bytes

        logger.info("[vector] Upserting %s points to collection %s", len(points), self.collection)

        # Retry solo su errori transitori: 5xx / 429 del server o errori di rete. I 4xx
        # client (dati malformati, incluso un payload oltre il limite di Qdrant)
        # propagano subito (vedi core/retry.should_retry): ritentare lo stesso batch
        # oversized fallirebbe sempre, quindi va risolto nel batching, non nel retry.
        def _is_transient(exc: BaseException) -> bool:
            if isinstance(exc, ConnectionError):
                return True
            code = getattr(exc, "status_code", None)
            return code is not None and (code >= 500 or code == 429)

        def _upsert(pts: List[PointStruct]) -> None:
            retry_sync(
                lambda: self.client.upsert(collection_name=self.collection, points=pts),
                retry_on=(UnexpectedResponse, ConnectionError),
                should_retry=_is_transient,
                what="qdrant upsert",
            )

        # Nessun batching richiesto (entrambi i limiti disattivati): utile nei test o su
        # collection con payload controllati.
        if batch_size <= 0 and max_bytes <= 0:
            _upsert(points)
            logger.info("[vector] Upsert complete")
            return

        # Batching size-aware: un batch accumula punti finche' non supera NE' il limite
        # di conteggio (batch_size) NE' quello di byte stimati (max_bytes). Senza il
        # limite sui byte, un documento grande produceva un singolo batch > 32 MiB che
        # Qdrant rifiutava con 400 (vedi qdrant_max_request_bytes).
        batch: List[PointStruct] = []
        batch_bytes = 0
        batch_index = 0

        def _flush() -> None:
            nonlocal batch, batch_bytes, batch_index
            if not batch:
                return
            batch_index += 1
            logger.info(
                "[vector] Upserting batch %s (%s points, ~%.1f MiB)",
                batch_index,
                len(batch),
                batch_bytes / (1024 * 1024),
            )
            _upsert(batch)
            batch = []
            batch_bytes = 0

        for point in points:
            size = _estimate_point_size(point)
            # Se aggiungere questo punto fa superare uno dei due limiti, svuota prima il
            # batch corrente. Un punto da solo oltre max_bytes viene comunque inviato
            # (non e' splittabile): se supera anche il limite hard di Qdrant sara' un 400
            # distinto, da risolvere alzando max_request_size_mb o riducendo la chunk size.
            if batch and (
                (max_bytes > 0 and batch_bytes + size > max_bytes)
                or (batch_size > 0 and len(batch) >= batch_size)
            ):
                _flush()
            batch.append(point)
            batch_bytes += size

        _flush()
        logger.info("[vector] Upsert complete")

    def search(self, vector: List[float], top_k: int = 10, filter=None) -> List[dict]:
        logger.debug("[vector] Searching top %s in collection %s", top_k, self.collection)
        results = self.client.search(
            collection_name=self.collection,
            query_vector=self._dense_query(vector),
            limit=top_k,
            query_filter=filter,
            with_payload=True,
        )
        logger.debug("[vector] Search returned %s results", len(results))
        return [
            {
                "id": r.id,
                "score": r.score,
                "payload": r.payload,
            }
            for r in results
        ]

    def search_hybrid(
        self,
        dense_vector: List[float],
        sparse_vector: SparseVector,
        top_k: int = 10,
        filter=None,
    ) -> List[dict]:
        if not settings.qdrant_enable_native_sparse:
            return self.search(dense_vector, top_k=top_k, filter=filter)

        logger.debug("[vector] Hybrid searching top %s in collection %s", top_k, self.collection)
        try:
            response = self.client.query_points(
                collection_name=self.collection,
                prefetch=[
                    Prefetch(
                        query=dense_vector,
                        using=settings.qdrant_dense_vector_name,
                        filter=filter,
                        limit=top_k,
                    ),
                    Prefetch(
                        query=sparse_vector,
                        using=settings.qdrant_sparse_vector_name,
                        filter=filter,
                        limit=top_k,
                    ),
                ],
                query=FusionQuery(fusion=Fusion.RRF),
                limit=top_k,
                with_payload=True,
            )
        except UnexpectedResponse:
            logger.exception("[vector] Native hybrid search failed; falling back to dense search")
            return self.search(dense_vector, top_k=top_k, filter=filter)
        points = getattr(response, "points", [])
        return [
            {
                "id": point.id,
                "score": point.score,
                "payload": point.payload,
            }
            for point in points
        ]

    def build_point_vector(self, dense_vector: List[float], sparse_vector: Optional[SparseVector] = None):
        if not settings.qdrant_enable_native_sparse:
            return dense_vector
        vector = {settings.qdrant_dense_vector_name: dense_vector}
        if sparse_vector is not None:
            vector[settings.qdrant_sparse_vector_name] = sparse_vector
        return vector

    def delete_by_document(self, document_id: str):
        logger.info("[vector] Deleting vectors for document_id=%s", document_id)
        self.client.delete(
            collection_name=self.collection,
            points_selector=Filter(
                must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]
            ),
        )
        logger.info("[vector] Deleted vectors for document_id=%s", document_id)

    def count(self, user_id: Optional[str] = None) -> int:
        result = self.client.count(
            collection_name=self.collection,
            count_filter=self.build_user_filter(user_id),
            exact=True,
        )
        return result.count

    def build_document_filter(self, document_id: str, user_id: Optional[str] = None) -> Filter:
        conditions = [FieldCondition(key="document_id", match=MatchValue(value=document_id))]
        if user_id:
            conditions.append(FieldCondition(key="user_id", match=MatchValue(value=user_id)))
        return Filter(must=conditions)

    def build_user_filter(self, user_id: Optional[str]) -> Optional[Filter]:
        if not user_id:
            return None
        return Filter(must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))])

    def reset_collection(self):
        logger.warning("[vector] Resetting collection %s", self.collection)
        self._client.delete_collection(collection_name=self.collection)
        self._ensure_collection()
        logger.warning("[vector] Collection %s reset complete", self.collection)

    def _dense_query(self, vector: List[float]):
        if not settings.qdrant_enable_native_sparse:
            return vector
        return NamedVector(name=settings.qdrant_dense_vector_name, vector=vector)

    def health(self):
        """Verify Qdrant connectivity by listing collections."""
        return self.client.get_collections()


vector_store = VectorStore()
