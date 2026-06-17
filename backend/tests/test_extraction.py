from app.services.extraction import _normalize_extraction


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
