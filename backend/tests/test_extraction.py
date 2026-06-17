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
