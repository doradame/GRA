import pytest

from app.services.agent.router import semantic_router


@pytest.mark.asyncio
async def test_router_direct_greeting():
    state = {"user_query": "ciao", "messages": [{"role": "user", "content": "ciao"}]}
    result = await semantic_router(state)
    assert result["intent"] == "direct"


@pytest.mark.asyncio
async def test_router_relational_keywords():
    state = {"user_query": "Quali sistemi dipendono dal firewall?", "messages": []}
    result = await semantic_router(state)
    assert result["intent"] == "relational"


@pytest.mark.asyncio
async def test_router_summary_keywords():
    state = {"user_query": "Quali sono i temi principali?", "messages": []}
    result = await semantic_router(state)
    assert result["intent"] == "summary"


@pytest.mark.asyncio
async def test_router_factual_fallback():
    state = {"user_query": "Cosa dice il documento sui requisiti?", "messages": []}
    result = await semantic_router(state)
    assert result["intent"] == "factual"
