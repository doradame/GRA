import pytest

import app.services.agent.tools.cypher_tool as cypher_tool_module
from app.services.agent.state import CypherToolResult, VectorToolResult
from app.services.agent.tools.cypher_tool import run_cypher_tool, validate_cypher


def test_validate_valid_read_query():
    cypher = """
    MATCH (fw:Entity)-[:DIPENDE_DA|BLOCCATO_DA]-(sys:Entity)
    WHERE toLower(fw.name) CONTAINS toLower($term)
    RETURN sys.name AS sistema
    LIMIT 20
    """
    assert validate_cypher(cypher) is True


def test_validate_rejects_write_query():
    cypher = "MATCH (n) DELETE n"
    assert validate_cypher(cypher) is False


def test_validate_rejects_merge():
    cypher = "MERGE (n:Entity {name: 'test'}) RETURN n"
    assert validate_cypher(cypher) is False


def test_validate_rejects_non_match_start():
    cypher = "RETURN 1"
    assert validate_cypher(cypher) is False


def test_validate_empty_query():
    assert validate_cypher("") is False


@pytest.mark.asyncio
async def test_run_cypher_tool_always_also_runs_vector_search(monkeypatch):
    captured_calls = []

    async def fake_cypher_tool(query):
        captured_calls.append(("cypher", query))
        return CypherToolResult(
            cypher="MATCH (e:Entity) WHERE toLower(e.name) CONTAINS toLower($term) RETURN e.name AS responsabile LIMIT 1",
            results=[{"responsabile": "Aurora-7"}],
            summary="- responsabile: Aurora-7",
            error=None,
        )

    async def fake_vector_tool(query, user_id=None):
        captured_calls.append(("vector", query, user_id))
        return VectorToolResult(
            chunks=[{"id": "chunk-1", "text": "Il responsabile tecnico è Mario Rossi."}],
            local_graph_facts=[],
            context="Il responsabile tecnico è Mario Rossi.",
            citations=[],
        )

    monkeypatch.setattr(cypher_tool_module, "cypher_tool", fake_cypher_tool)
    monkeypatch.setattr(cypher_tool_module, "vector_tool", fake_vector_tool)

    state = {"user_query": "Chi è il responsabile tecnico del progetto Aurora-7?", "user_id": "user-1"}
    result = await run_cypher_tool(state)

    assert {call[0] for call in captured_calls} == {"cypher", "vector"}
    assert result["cypher_results"].results == [{"responsabile": "Aurora-7"}]
    assert "Mario Rossi" in result["vector_results"].context
