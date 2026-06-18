from unittest.mock import MagicMock, patch

import pytest

from app.services.agent.tools.vector_tool import _fetch_local_graph_facts


@pytest.fixture
def mock_graph_store():
    store = MagicMock()
    store._stringify_name = lambda x: str(x) if x else ""
    store.driver.session.return_value.__enter__.return_value.run.return_value = [
        {"source": "Firewall DMZ", "rel_type": "DIPENDE_DA", "target": "Server Web"},
        {"source": "Firewall DMZ", "rel_type": "DIPENDE_DA", "target": "Server Web"},  # duplicato
        {"source": "Server Web", "rel_type": "CONNESSO_A", "target": "Database"},
    ]
    return store


def test_fetch_local_graph_facts_dedup_and_limit(monkeypatch, mock_graph_store):
    monkeypatch.setattr("app.services.agent.tools.vector_tool.graph_store", mock_graph_store)
    facts = _fetch_local_graph_facts(["chunk-1", "chunk-2"])
    assert len(facts) == 2
    assert "Firewall DMZ --[DIPENDE_DA]--> Server Web" in facts
    assert "Server Web --[CONNESSO_A]--> Database" in facts
