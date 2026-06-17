from qdrant_client.models import FieldCondition, MatchValue

from app.services.vector_store import VectorStore


def test_build_user_filter_scopes_payload_by_user_id():
    store = VectorStore()

    query_filter = store.build_user_filter("user-1")

    assert query_filter is not None
    assert query_filter.must == [
        FieldCondition(key="user_id", match=MatchValue(value="user-1"))
    ]


def test_build_user_filter_returns_none_for_service_scope():
    store = VectorStore()

    assert store.build_user_filter(None) is None
