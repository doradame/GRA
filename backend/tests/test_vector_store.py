from unittest.mock import MagicMock

from qdrant_client.models import FieldCondition, MatchValue, PointStruct

from app.services.vector_store import VectorStore, _estimate_point_size


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


def test_upsert_splits_points_into_batches():
    store = VectorStore()
    mock_client = MagicMock()
    store._client = mock_client

    points = [
        PointStruct(id=str(i), vector=[0.0] * 3, payload={"text": f"chunk-{i}"})
        for i in range(250)
    ]

    store.upsert(points, batch_size=100)

    assert mock_client.upsert.call_count == 3
    call_args = [call.kwargs["points"] for call in mock_client.upsert.call_args_list]
    assert len(call_args[0]) == 100
    assert len(call_args[1]) == 100
    assert len(call_args[2]) == 50


def test_upsert_splits_points_by_estimated_size(monkeypatch):
    # Regressione per il bug del documento grande: un batch superava il limite 32 MiB di
    # Qdrant perche' il batching era solo a conteggio. Con un size-cap basso (e count-cap
    # irrilevante) deve guidare lo split la stima dei byte, non il numero di punti.
    import app.services.vector_store as vs

    store = VectorStore()
    mock_client = MagicMock()
    store._client = mock_client
    monkeypatch.setattr(vs.settings, "qdrant_max_request_bytes", 500)

    points = [
        PointStruct(id=str(i), vector=[0.0] * 3, payload={"text": f"chunk-{i}"})
        for i in range(20)
    ]

    store.upsert(points, batch_size=1000)

    calls = [call.kwargs["points"] for call in mock_client.upsert.call_args_list]
    # lo split e' avvenuto per size, non in un unico batch
    assert len(calls) > 1
    # ogni batch rispetta il size-cap
    for batch in calls:
        assert sum(_estimate_point_size(p) for p in batch) <= 500
    # tutti i point inviati esattamente una volta
    flat = [p for batch in calls for p in batch]
    assert len(flat) == 20
    assert set(str(p.id) for p in flat) == {str(i) for i in range(20)}
