import os
import json
import httpx
from mcp.server.fastmcp import FastMCP

BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000")
API_KEY = os.environ.get("API_KEY", "mcpsecret")

mcp = FastMCP("insurance-graph-rag")


async def call_backend(method: str, path: str, json_data: dict = None, params: dict = None):
    async with httpx.AsyncClient(timeout=60.0) as client:
        headers = {"X-MCP-API-Key": API_KEY}
        if method == "GET":
            response = await client.get(f"{BACKEND_URL}{path}", params=params, headers=headers)
        else:
            response = await client.post(f"{BACKEND_URL}{path}", json=json_data, headers=headers)
        response.raise_for_status()
        return response.json()


@mcp.tool()
async def search_knowledge_base(query: str, top_k: int = 8) -> str:
    """Cerca nella knowledge base e restituisce chunk, file, score e metadati senza generare una risposta."""
    data = await call_backend(
        "GET",
        "/api/v1/kb/search",
        params={"query": query, "top_k": max(1, min(top_k, 24))},
    )
    return json.dumps(data, ensure_ascii=False, indent=2)


@mcp.tool()
async def answer_knowledge_base(query: str) -> str:
    """Risponde usando la knowledge base e restituisce anche le citazioni usate."""
    data = await call_backend(
        "POST",
        "/api/v1/chat/completions",
        json_data={
            "messages": [{"role": "user", "content": query}],
            "stream": False,
        },
    )
    answer = data["choices"][0]["message"]["content"]
    citations = data.get("citations", [])
    result = {"answer": answer, "citations": citations}
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def query_knowledge_base(query: str) -> str:
    """Compatibilità: alias di answer_knowledge_base."""
    return await answer_knowledge_base(query)


@mcp.tool()
async def explore_graph(entity: str) -> str:
    """Esplora il grafo di conoscenza a partire da un'entità."""
    data = await call_backend("GET", "/api/v1/graph/explore", params={"entity": entity})
    return json.dumps(data, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "sse")
    mcp.run(transport=transport)
