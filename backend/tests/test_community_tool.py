from unittest.mock import MagicMock

import pytest

from app.services.agent.tools.community_tool import community_tool


@pytest.fixture
def mock_graph_store():
    store = MagicMock()
    store.driver.session.return_value.__enter__.return_value.run.return_value = [
        {
            "community_id": "root-1",
            "summary": "Riassunto globale del KB.",
            "entity_count": 42,
            "relation_count": 10,
            "updated_at": "2026-06-19",
        }
    ]
    return store


@pytest.mark.asyncio
async def test_community_tool_uses_root_summaries_without_vector_search(monkeypatch, mock_graph_store):
    monkeypatch.setattr("app.services.agent.tools.community_tool.graph_store", mock_graph_store)

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("embed_text non dovrebbe essere chiamato se esistono riassunti root")

    monkeypatch.setattr("app.services.agent.tools.community_tool.embed_text", fail_if_called)

    result = await community_tool(query="Di cosa parla questo KB?")

    assert result.community_ids == ["root-1"]
    assert "Riassunto globale del KB." in result.summaries
    assert "Riassunto globale del KB." in result.context


@pytest.mark.asyncio
async def test_community_tool_falls_back_to_vector_search_without_root_summaries(monkeypatch):
    store = MagicMock()
    # Prima query (_fetch_root_community_summaries) non trova nulla.
    store.driver.session.return_value.__enter__.return_value.run.return_value = []
    monkeypatch.setattr("app.services.agent.tools.community_tool.graph_store", store)

    async def fake_embed_text(query):
        return [0.1, 0.2, 0.3]

    monkeypatch.setattr("app.services.agent.tools.community_tool.embed_text", fake_embed_text)
    monkeypatch.setattr("app.services.agent.tools.community_tool.build_query_sparse_vector", lambda q: None)
    monkeypatch.setattr(
        "app.services.agent.tools.community_tool.vector_store",
        MagicMock(
            build_user_filter=lambda user_id: None,
            search_hybrid=lambda *a, **k: [],
            search=lambda *a, **k: [],
        ),
    )

    result = await community_tool(query="Qualcosa di molto specifico", user_id=None)

    assert result.community_ids == []
    assert result.context == ""
