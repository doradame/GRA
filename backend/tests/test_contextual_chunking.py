from types import SimpleNamespace

import pytest

import app.services.contextual_chunking as contextual_chunking_module
from app.services.contextual_chunking import generate_chunk_contexts


@pytest.mark.asyncio
async def test_generate_chunk_contexts_returns_empty_strings_without_openai_key(monkeypatch):
    monkeypatch.setattr(contextual_chunking_module.settings, "openai_api_key", "")

    result = await generate_chunk_contexts("documento completo", ["chunk uno", "chunk due"])

    assert result == ["", ""]


@pytest.mark.asyncio
async def test_generate_chunk_contexts_returns_empty_strings_in_demo_mode(monkeypatch):
    monkeypatch.setattr(contextual_chunking_module.settings, "openai_api_key", "sk-test-demo")

    result = await generate_chunk_contexts("documento completo", ["chunk uno"])

    assert result == [""]


@pytest.mark.asyncio
async def test_generate_chunk_contexts_calls_llm_per_chunk_and_tracks_usage(monkeypatch):
    monkeypatch.setattr(contextual_chunking_module.settings, "openai_api_key", "sk-real")
    captured_prompts = []
    tracked_calls = []

    async def fake_create(model, messages, temperature, max_tokens):
        captured_prompts.append(messages[0]["content"])
        content = f"Contesto per: {messages[0]['content'][-20:]}"
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(total_tokens=42),
        )

    monkeypatch.setattr(contextual_chunking_module.client.chat.completions, "create", fake_create)
    monkeypatch.setattr(
        contextual_chunking_module, "increment_contextual_retrieval_calls", lambda tokens=0: tracked_calls.append(tokens)
    )

    result = await generate_chunk_contexts("documento completo", ["chunk uno", "chunk due"])

    assert len(result) == 2
    assert all(r.startswith("Contesto per:") for r in result)
    assert len(captured_prompts) == 2
    assert tracked_calls == [42, 42]


@pytest.mark.asyncio
async def test_generate_chunk_contexts_falls_back_to_empty_string_on_llm_error(monkeypatch):
    monkeypatch.setattr(contextual_chunking_module.settings, "openai_api_key", "sk-real")

    async def failing_create(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(contextual_chunking_module.client.chat.completions, "create", failing_create)

    result = await generate_chunk_contexts("documento completo", ["chunk uno"])

    assert result == [""]


@pytest.mark.asyncio
async def test_generate_chunk_contexts_truncates_document_to_configured_limit(monkeypatch):
    monkeypatch.setattr(contextual_chunking_module.settings, "openai_api_key", "sk-real")
    monkeypatch.setattr(contextual_chunking_module.settings, "contextual_retrieval_max_doc_chars", 10)
    captured_prompts = []

    async def fake_create(model, messages, temperature, max_tokens):
        captured_prompts.append(messages[0]["content"])
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=None,
        )

    monkeypatch.setattr(contextual_chunking_module.client.chat.completions, "create", fake_create)

    long_document = "x" * 1000
    await generate_chunk_contexts(long_document, ["chunk"])

    assert "x" * 1000 not in captured_prompts[0]
    assert "x" * 10 in captured_prompts[0]
