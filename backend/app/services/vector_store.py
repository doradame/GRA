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
)
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

VECTOR_SIZE = settings.embedding_dimensions


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

    def upsert(self, points: List[PointStruct], batch_size: Optional[int] = None):
        if batch_size is None:
            batch_size = settings.qdrant_upsert_batch_size

        logger.info("[vector] Upserting %s points to collection %s", len(points), self.collection)

        if batch_size <= 0:
            self.client.upsert(collection_name=self.collection, points=points)
        else:
            for i in range(0, len(points), batch_size):
                batch = points[i : i + batch_size]
                logger.info(
                    "[vector] Upserting batch %s-%s of %s points",
                    i + 1,
                    i + len(batch),
                    len(points),
                )
                self.client.upsert(collection_name=self.collection, points=batch)

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
        self.client.delete_collection(collection_name=self.collection)
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
