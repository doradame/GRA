import os
import uuid

import pytest
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, Fusion, FusionQuery, PointStruct, Prefetch, SparseVectorParams, VectorParams

from app.services.sparse_vectors import build_sparse_vector


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 to run Qdrant integration tests",
)


def test_qdrant_accepts_dense_sparse_and_fusion_query():
    client = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))
    collection = f"test_hybrid_{uuid.uuid4().hex}"
    try:
        client.create_collection(
            collection_name=collection,
            vectors_config={"dense": VectorParams(size=3, distance=Distance.COSINE)},
            sparse_vectors_config={"text_sparse": SparseVectorParams()},
        )
        client.upsert(
            collection_name=collection,
            points=[
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector={
                        "dense": [0.1, 0.2, 0.3],
                        "text_sparse": build_sparse_vector("risk approval"),
                    },
                    payload={"text": "risk approval"},
                )
            ],
        )
        response = client.query_points(
            collection_name=collection,
            prefetch=[
                Prefetch(query=[0.1, 0.2, 0.3], using="dense", limit=5),
                Prefetch(query=build_sparse_vector("risk"), using="text_sparse", limit=5),
            ],
            query=FusionQuery(fusion=Fusion.RRF),
            limit=5,
        )
        assert response.points
    finally:
        client.delete_collection(collection_name=collection)
