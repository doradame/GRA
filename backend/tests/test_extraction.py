import asyncio

import app.services.extraction as extraction
from app.services.extraction import _normalize_extraction, extract_relations_batch


def test_normalize_extraction_canonicalizes_entities_and_relations():
    data = {
        "entities": [
            {"id": "a", "name": "ACME S.p.A.", "type": "Organization"},
            {"id": "b", "name": "  ACME S.p.A.  ", "type": "Organization"},
            {"id": "c", "name": "Policy X", "type": "Rule"},
        ],
        "relations": [
            {"source_id": "a", "target_id": "c", "type": "requires", "properties": {}},
            {"source_id": "b", "target_id": "c", "type": "requires", "properties": {}},
            {"source_id": "missing", "target_id": "c", "type": "requires", "properties": {}},
        ],
    }

    normalized = _normalize_extraction(data)

    assert len(normalized["entities"]) == 2
    assert len(normalized["relations"]) == 1
    assert normalized["relations"][0]["source_id"] == normalized["entities"][0]["id"]


def test_normalize_extraction_accepts_string_entities_and_skips_bad_relations():
    data = {
        "entities": ["ACME S.p.A.", {"id": "policy", "name": "Policy X", "type": "Rule"}, 42],
        "relations": ["ACME requires Policy X", {"source_id": "missing", "target_id": "policy", "type": "requires"}],
    }

    normalized = _normalize_extraction(data)

    assert [entity["name"] for entity in normalized["entities"]] == ["ACME S.p.A.", "Policy X"]
    assert normalized["relations"] == []


def test_normalize_extraction_accepts_entity_mapping():
    data = {
        "entities": {
            "company": {"id": "company", "name": "ACME S.p.A.", "type": "Organization"},
            "policy": "Policy X",
        },
        "relations": [],
    }

    normalized = _normalize_extraction(data)

    assert [entity["name"] for entity in normalized["entities"]] == ["ACME S.p.A.", "Policy X"]


def test_normalize_extraction_rejects_non_object_payload():
    assert _normalize_extraction(["ACME"]) == {"entities": [], "relations": []}


def test_extract_relations_batch_demo_mode_returns_empty_per_chunk(monkeypatch):
    monkeypatch.setattr(extraction.settings, "openai_api_key", "sk-test")
    items = [("c1", [{"id": "a"}, {"id": "b"}]), ("c2", [])]

    result = asyncio.run(extract_relations_batch(items))

    assert result == [[], []]


def test_extract_relations_batch_preserves_order_and_runs_concurrently(monkeypatch):
    monkeypatch.setattr(extraction.settings, "openai_api_key", "real-key")
    monkeypatch.setattr(extraction.settings, "extraction_concurrency", 2)

    state = {"active": 0, "max_active": 0}

    async def fake_worker(client, chunk_text, entities):
        state["active"] += 1
        state["max_active"] = max(state["max_active"], state["active"])
        await asyncio.sleep(0)
        state["active"] -= 1
        return [{"source_id": "x", "target_id": "y", "type": chunk_text, "properties": {}}] if entities else []

    monkeypatch.setattr(extraction, "_extract_relations_with_client", fake_worker)

    class _FakeClient:
        async def close(self):
            pass

    monkeypatch.setattr(extraction, "AsyncOpenAI", lambda **kw: _FakeClient())

    items = [(f"chunk {i}", [{"id": "a"}, {"id": "b"}]) for i in range(5)]
    result = asyncio.run(extract_relations_batch(items))

    # Ordine e contenuto per-chunk preservati.
    assert len(result) == 5
    assert [r[0]["type"] for r in result] == [f"chunk {i}" for i in range(5)]
    # Concurrency=2 su 5 chunk: almeno 2 worker in parallelo.
    assert state["max_active"] >= 2
