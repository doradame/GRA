# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Self-hosted Graph RAG stack: upload documents, the backend ingests them into a vector store (Qdrant) and a knowledge graph (Neo4j), and a LangGraph agent answers questions through an OpenAI-compatible chat endpoint consumed by LibreChat, an admin UI, and an MCP server.

## Commands

### Backend (FastAPI, Python)
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload          # run API locally
pytest                                  # unit tests (no external services needed)
pytest tests/test_rag_engine.py -k foo  # single test
alembic upgrade head                    # apply DB migrations
alembic revision -m "message"           # new migration
```

Two test tiers are gated by env vars and require services from `docker-compose.integration.yml`:
```bash
docker compose -f docker-compose.integration.yml up -d
RUN_INTEGRATION_TESTS=1 pytest tests/test_qdrant_integration.py
RUN_E2E_TESTS=1 pytest tests/test_ingestion_e2e.py   # runs scripts/e2e_ingestion_smoke.py
```
The integration compose file exposes test-only ports: Postgres `15432`, Neo4j `17687`, Qdrant `16333`, MinIO `19000`, Redis `16379`.

### Admin UI (React + Vite + TS)
```bash
cd admin
npm install
npm run dev     # local dev server
npm run build   # type-check + build (treat as the CI gate for this package)
```

### Full stack (Docker)
```bash
docker compose up -d                          # everything: backend, worker, admin, mcp, librechat, infra
docker compose logs -f backend worker         # API + ingestion worker logs
docker compose -f docker-compose.integration.yml up -d   # ephemeral infra for backend integration/e2e tests
```
`OPENAI_API_KEY=sk-test` runs the system in demo mode (deterministic fake embeddings/LLM responses) — useful to verify the stack is wired correctly without burning real API calls.

## Architecture

### Services (docker-compose.yml)
- `backend` — FastAPI app (`backend/app`), built from `backend/Dockerfile`.
- `worker` — Celery worker (`celery -A app.core.celery_app worker`) running ingestion, entity resolution, and community detection jobs. Concurrency is fixed at `-c 1`; shares the same image/code as `backend`.
- `admin` — Vite/React panel for uploads, ingestion status, graph exploration.
- `mcp` — standalone MCP server (`mcp_server/server.py`) that proxies to the backend's REST API using an `X-MCP-API-Key` header.
- `caddy` — reverse proxy / TLS termination in front of backend, admin, and librechat.
- `librechat` + `librechat-admin` + `mongo` + `meilisearch` — chat frontend, configured via `librechat/librechat.yaml` to call the backend as a custom OpenAI endpoint.
- `db` (Postgres), `neo4j`, `qdrant`, `minio`, `redis` — storage/infra.

All persistent state lives under bind-mounted `./data/`; never commit its contents.

### Backend layout (`backend/app/`)
- `routers/` — FastAPI route modules grouped by domain (`auth`, `documents`, `chat`, `graph`, `kb`). Mounted in `main.py` under `/api/v1/...`.
- `core/` — settings (`config.py`, a pydantic `Settings` object read from env/`.env`), DB engine (`database.py`), JWT/auth (`auth.py`), Celery app wiring (`celery_app.py`).
- `models/` — SQLAlchemy ORM models (`models.py`: `User`, `Document`, `Chunk`, `IngestionJob`) and Pydantic schemas (`schemas.py`).
- `services/` — ingestion and retrieval logic (see below).
- `services/agent/` — the LangGraph orchestration layer.
- `tasks/` — Celery task wrappers around the async services (ingestion, entity resolution, community detection); tasks are sync entrypoints that `asyncio.run(...)` the underlying async service functions.

### Auth model
Three credential paths are accepted by `get_current_user_or_mcp` (`core/auth.py`): a normal JWT bearer token (real users via `get_current_user`), a static `X-MCP-API-Key` header (maps to a synthetic `mcp@internal` user), or a static bearer token equal to `LIBRECHAT_API_KEY` (maps to a synthetic `librechat@...` user). Both synthetic users are treated as "no per-user filter" — see `_retrieval_user_id` in `routers/chat.py` and `routers/kb.py`, which returns `None` instead of a user id for these accounts so MCP/LibreChat see the whole KB rather than a single owner's documents. Real users only ever see documents they uploaded (`created_by` filter applied through Qdrant/Neo4j filters).

### Ingestion pipeline (`services/ingestion.py`, run via Celery in `tasks/ingestion.py`)
Sequential phases tracked on `Document.status` / `IngestionJob` (`services/ingestion.py` `STATUS_*` constants, with `PHASE_PROGRESS` percentages surfaced to the admin UI):
1. `parsing` — `services/parsing.py` extracts text (+ optional OCR, gated by `ENABLE_OCR`/`MIN_TEXT_CHARS_FOR_OCR`) and per-page spans.
2. `chunking` — `services/chunking.py` splits text into chunks, tracking char/page spans for citations.
3. `embedding` — `services/embeddings.py` (OpenAI embeddings, batched via `EMBEDDING_BATCH_SIZE`) plus `services/sparse_vectors.py` (BM25-like sparse vectors: NLTK tokenization, BLAKE2b hashed buckets, IDF over the chunk corpus, L2-normalized). Before embedding, each chunk is prefixed with a "contextual retrieval" header built by `ingestion._build_document_context`/`_build_chunk_embedding_input` — document filename + the user-supplied `category`/`description` (set at upload time, see `Document.category`/`Document.description`) + the chunk's inferred section title. This contextualized text is only the embedding/sparse-vector *input*; the chunk's stored `text` (Postgres + Qdrant payload, used for citations and LLM context) stays unmodified.
4. `vector_indexing` — upsert dense+sparse vectors into Qdrant (`services/vector_store.py`), batched via `QDRANT_UPSERT_BATCH_SIZE`.
5. `graph_indexing` — entity extraction via GLiNER (`services/gliner_extraction.py`) plus relation extraction via LLM (`services/extraction.py`), both running over *all* chunks (no chunk cap — capping previously left most entities in long documents without any entity-entity relation), written into Neo4j (`services/graph_store.py`). Entity IDs are `SHA256(type:name)` to stay consistent across both extraction paths.
6. `completed` / `error`.

Two background tasks operate on the graph after ingestion, both admin-only and Celery-driven (`routers/graph.py`):
- Entity resolution (`tasks/entity_resolution.py`, `services/entity_resolution.py`): embeds entity names, cosine-similarity clusters above a threshold (default `0.93`), merges via `apoc.refactor.mergeNodes`.
- Community detection (`tasks/community_detection.py`, `services/community_detection.py`): Louvain (or configured algorithm) over the graph, then LLM-summarized into `CommunitySummary` nodes, capped at `COMMUNITY_SUMMARY_MAX_ENTITIES` entities per summary.

### Agentic retrieval (`services/agent/`)
A LangGraph `StateGraph` (`agent/graph.py`) compiled once at import time as `agent_graph`, invoked from `services/rag_engine.chat_completion`. Flow:
1. `semantic_router` (`agent/router.py`) — LLM-classifies the latest user message into `direct | factual | relational | summary` (falls back to keyword heuristics in demo mode or on LLM failure).
2. Routed to one of three tools (`agent/tools/`), each returning a typed result (`agent/state.py`):
   - `vector_tool` — hybrid dense+sparse Qdrant search, the default "factual" path.
   - `text2cypher_tool` — LLM-generated Cypher against Neo4j for relational questions, with retry budget `AGENT_CYPHER_MAX_RETRIES`.
   - `community_tool` — pulls `CommunitySummary` nodes for "summary"/overview questions.
   - `direct` intent skips tools entirely and answers directly.
3. `synthesizer` (`agent/nodes.py`) — merges tool output into final `context`/`citations`/`answer`, capped via `AGENT_MAX_GRAPH_FACTS` / `AGENT_MAX_COMMUNITY_SUMMARIES`.

`AgentState` (TypedDict in `agent/state.py`) is the contract threaded through every node — when adding a new tool/intent, extend this state, add a node, and wire it into `agent/graph.py`'s conditional edges.

`rag_engine.build_context` (used directly by `/api/v1/kb/search` for citation-only lookups, independent of the agent graph) does hybrid retrieval + reranking + lightweight regex-based entity expansion into the graph — this is a simpler, non-agentic retrieval path kept separate from the LangGraph flow.

### Reranking
Both retrieval paths (`vector_tool` and `rag_engine.build_context`) rerank the oversampled hybrid-search candidates with a local cross-encoder (`services/reranker.py`, lazy-loaded via `sentence-transformers`, default model `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` — multilingual, CPU-friendly, configurable via `RERANKER_MODEL`). If the model fails to load or `ENABLE_RERANKER=false`, both call sites fall back to the cheaper lexical rerank in `services/retrieval_utils.py` (`rerank_hybrid`, Jaccard token overlap blended with vector score).

### Config
All tunables are centralized in `backend/app/core/config.py` (`Settings`, a `pydantic_settings.BaseSettings` reading `.env`) and mirrored as environment variables for each service in `docker-compose.yml`. When adding a new tunable, add it in both places.

### MCP server (`mcp_server/server.py`)
A thin FastMCP wrapper that calls the backend's REST API over HTTP (not in-process) using `X-MCP-API-Key`. Exposes `search_knowledge_base`, `answer_knowledge_base`, `query_knowledge_base` (alias), `explore_graph`. Public access goes through Caddy at `/sse`; LibreChat talks to it over the internal Docker network.

## Coding conventions

- Python: 4-space indent, type hints where practical, `snake_case` for modules/functions/Celery tasks; FastAPI endpoints grouped by domain in router modules.
- TypeScript/React: function components with `PascalCase` filenames, `camelCase` variables, Tailwind utility classes (see `admin/src/components/`).

## Notes

- Backend auto-creates Postgres tables on startup when `AUTO_CREATE_TABLES=true` (dev default) — production should rely on Alembic instead.
- Do not commit `.env`, secrets, database dumps, uploaded documents, or anything under `data/`.
