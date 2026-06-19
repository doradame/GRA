from types import SimpleNamespace

import pytest

import app.services.agent.nodes as nodes_module
from app.services.agent.nodes import critic_node


@pytest.mark.asyncio
async def test_critic_node_sufficient_in_demo_mode(monkeypatch):
    monkeypatch.setattr(nodes_module.settings, "openai_api_key", "")

    result = await critic_node({"user_query": "domanda", "context": "", "answer": "", "iteration": 0})

    assert result["critic_verdict"] == "sufficient"
    assert result["iteration"] == 1


@pytest.mark.asyncio
async def test_critic_node_sufficient_when_iteration_budget_exhausted(monkeypatch):
    monkeypatch.setattr(nodes_module.settings, "openai_api_key", "sk-real")
    monkeypatch.setattr(nodes_module.settings, "agent_max_iterations", 2)

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("non dovrebbe chiamare l'LLM se il budget di iterazioni è esaurito")

    monkeypatch.setattr(nodes_module.client.chat.completions, "create", fail_if_called)

    result = await critic_node({"user_query": "domanda", "context": "ctx", "answer": "risposta", "iteration": 1})

    assert result["critic_verdict"] == "sufficient"
    assert result["iteration"] == 2


@pytest.mark.asyncio
async def test_critic_node_marks_insufficient_and_sets_refined_query(monkeypatch):
    monkeypatch.setattr(nodes_module.settings, "openai_api_key", "sk-real")
    monkeypatch.setattr(nodes_module.settings, "agent_max_iterations", 3)

    async def fake_create(model, messages, temperature, response_format):
        content = '{"sufficient": false, "reasoning": "manca un dettaglio", "refined_query": "domanda più specifica"}'
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    monkeypatch.setattr(nodes_module.client.chat.completions, "create", fake_create)

    result = await critic_node(
        {"user_query": "domanda originale", "context": "contesto parziale", "answer": "risposta incompleta", "iteration": 0}
    )

    assert result["critic_verdict"] == "insufficient"
    assert result["critic_reasoning"] == "manca un dettaglio"
    assert result["user_query"] == "domanda più specifica"
    assert result["iteration"] == 1


@pytest.mark.asyncio
async def test_critic_node_marks_sufficient_without_touching_user_query(monkeypatch):
    monkeypatch.setattr(nodes_module.settings, "openai_api_key", "sk-real")
    monkeypatch.setattr(nodes_module.settings, "agent_max_iterations", 3)

    async def fake_create(model, messages, temperature, response_format):
        content = '{"sufficient": true, "reasoning": "contesto adeguato"}'
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    monkeypatch.setattr(nodes_module.client.chat.completions, "create", fake_create)

    result = await critic_node(
        {"user_query": "domanda originale", "context": "contesto completo", "answer": "risposta", "iteration": 0}
    )

    assert result["critic_verdict"] == "sufficient"
    assert result["user_query"] == "domanda originale"


@pytest.mark.asyncio
async def test_critic_node_falls_back_to_sufficient_on_llm_error(monkeypatch):
    monkeypatch.setattr(nodes_module.settings, "openai_api_key", "sk-real")
    monkeypatch.setattr(nodes_module.settings, "agent_max_iterations", 3)

    async def failing_create(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(nodes_module.client.chat.completions, "create", failing_create)

    result = await critic_node({"user_query": "domanda", "context": "ctx", "answer": "risposta", "iteration": 0})

    assert result["critic_verdict"] == "sufficient"
