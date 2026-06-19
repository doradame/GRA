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
3. `embedding` — `services/embeddings.py` (OpenAI embeddings, batched via `EMBEDDING_BATCH_SIZE`) plus `services/sparse_vectors.py` (real BM25 sparse vectors: NLTK tokenization, IDF/avgdl computed over the *entire* indexed corpus — not just the current document — via a stable term vocabulary in `services/sparse_corpus_stats.py`: Postgres table `sparse_terms` maps term → permanent integer id, Redis caches `bm25:vocab`/`bm25:df`/`bm25:total_chunks`/`bm25:total_tokens` for fast query-time reads with no DB session needed. Each `Document` stores its own `sparse_term_counts`/`sparse_total_tokens` contribution so it can be cleanly subtracted from the global stats on delete/reindex — see `subtract_document_contribution`/`apply_document_delta`). On backend startup, if the Redis cache is missing or has drifted from `count(Chunk)` beyond `RECONCILE_BM25_TOLERANCE`, `reconcile_bm25_cache_if_needed` rebuilds it from Postgres (gated by `RECONCILE_BM25_ON_STARTUP`, fault-tolerant) — otherwise a flushed Redis would silently yield empty sparse vectors at query time. Before embedding, each chunk is prefixed with a "contextual retrieval" header built by `ingestion._build_document_context`/`_build_chunk_embedding_input` — document filename + the user-supplied `category`/`description` (set at upload time, see `Document.category`/`Document.description`) + the chunk's inferred section title. If `ENABLE_RICH_CONTEXTUAL_RETRIEVAL` is on (default), `services/contextual_chunking.py` also generates a 1-2 sentence LLM-written situational context per chunk (one chat-completion call per chunk, model `CONTEXTUAL_RETRIEVAL_MODEL`, document text capped at `CONTEXTUAL_RETRIEVAL_MAX_DOC_CHARS`, bounded concurrency via `CONTEXTUAL_RETRIEVAL_CONCURRENCY`), inserted between the section title and chunk text — falls back to an empty string (i.e. the cheap metadata-only header) in demo mode or on LLM failure. This contextualized text is only the embedding/sparse-vector *input*; the chunk's stored `text` (Postgres + Qdrant payload, used for citations and LLM context) stays unmodified.
4. `vector_indexing` — upsert dense+sparse vectors into Qdrant (`services/vector_store.py`), batched via `QDRANT_UPSERT_BATCH_SIZE`.
5. `graph_indexing` — entity extraction via GLiNER (`services/gliner_extraction.py`) plus relation extraction via LLM (`services/extraction.py`), both running over *all* chunks (no chunk cap — capping previously left most entities in long documents without any entity-entity relation), written into Neo4j (`services/graph_store.py`). Entity IDs are `SHA256(type:name)` to stay consistent across both extraction paths.
6. `completed` / `error`.

Two background tasks operate on the graph after ingestion, both admin-only and Celery-driven (`routers/graph.py`). Both are **guarded by a Redis distributed lock** (`core/locks.py`, key `lock:job:<name>`): the task acquires the lock (skipping with `status:"skipped"` if another run is in progress) and the router returns 409 on a best-effort pre-check. Both run with `max_retries=0` — they mutate the graph, so on failure the admin re-triggers manually instead of Celery auto-retrying a partially-destructive operation.
- Entity resolution (`tasks/entity_resolution.py`, `services/entity_resolution.py`): embeds entity names, cosine-similarity clusters above a threshold (default `0.93`), merges via `apoc.refactor.mergeNodes`. Each cluster's merges run in a **single Neo4j transaction** so a mid-group failure rolls back the whole cluster rather than leaving it partially merged.
- Community detection (`tasks/community_detection.py`, `services/community_detection.py`): Louvain (or configured algorithm) over the graph at **two hierarchy levels** — `leaf` (fine-grained, `community_louvain.best_partition`) and `root` (coarsest level of `community_louvain.generate_dendrogram`, the whole graph collapsed into a handful of communities) — each LLM-summarized into `CommunitySummary` nodes tagged with a `level` property, capped at `COMMUNITY_SUMMARY_MAX_ENTITIES` entities per summary. The rebuild is **non-destructive**: all summaries are generated in memory first (no Neo4j writes during the LLM phase, so a crash there leaves existing summaries intact), then persisted with idempotent `MERGE` (UUID5 ids `community-{level}-{comm_id}`, stable across runs) followed by a `delete-stale` (`WHERE id NOT IN new_ids`) that drops communities from previous runs whose ids are no longer valid. Louvain's community numbering isn't stable across runs, which is exactly the drift the delete-stale cleans up.

### Agentic retrieval (`services/agent/`)
A LangGraph `StateGraph` (`agent/graph.py`) compiled once at import time as `agent_graph`, invoked from `services/rag_engine.chat_completion`. Flow:
1. `semantic_router` (`agent/router.py`) — LLM-classifies the latest user message into `direct | factual | relational | summary` (falls back to keyword heuristics in demo mode or on LLM failure).
2. Routed to one of three tools (`agent/tools/`), each returning a typed result (`agent/state.py`):
   - `vector_tool` — hybrid dense+sparse Qdrant search, the default "factual" path.
   - `text2cypher_tool` — LLM-generated Cypher against Neo4j for relational questions, with retry budget `AGENT_CYPHER_MAX_RETRIES`; always also runs `vector_tool` in parallel as a grounding safety net (an LLM-generated Cypher query can "succeed" — no error — while being semantically wrong, e.g. matching the query term as an entity name instead of traversing a real relation).
   - `community_tool` — for "summary"/overview questions, tries `root`-level `CommunitySummary` nodes first (whole-KB coverage, no vector search needed); falls back to the old chunk-vector-search → mentioned-entities → `leaf`-level-community path only if no `root` summaries exist yet (community detection never ran). On sufficiently fragmented graphs, Louvain's dendrogram may only have one real level, so `root` ends up identical to `leaf` (handled correctly, just without the intended "few large communities" coarsening). The context fed to the LLM is phrased as "principali argomenti trattati" (not "community") to avoid leaking internal terminology into user-facing answers.
   - `direct` intent skips tools entirely and answers directly.
3. `synthesizer` (`agent/nodes.py`) — merges tool output into `context`/`citations`/`answer`, capped via `AGENT_MAX_GRAPH_FACTS` / `AGENT_MAX_COMMUNITY_SUMMARIES`.
4. `critic` (`agent/nodes.py::critic_node`) — LLM judges whether the draft answer/context is sufficient; if not (and the `AGENT_MAX_ITERATIONS` budget isn't exhausted), it rewrites `user_query` with a refined/decomposed query and routes back to the *same* tool node for another retrieval round (`graph.py::route_after_critic`) instead of ending. `direct` intent bypasses the critic entirely. The critic's view of `context`/`answer` is capped at 40000/12000 chars (not tighter) — a previous, much smaller cap (6000/2000) caused false "risposta tronca"/"fonte non nel contesto" verdicts once answers and context grew past it, silently tripling LLM calls per query.

`AgentState` (TypedDict in `agent/state.py`) is the contract threaded through every node — when adding a new tool/intent, extend this state, add a node, and wire it into `agent/graph.py`'s conditional edges.

`rag_engine.build_context` (used directly by `/api/v1/kb/search` for citation-only lookups, independent of the agent graph) does hybrid retrieval + reranking + lightweight regex-based entity expansion into the graph — this is a simpler, non-agentic retrieval path kept separate from the LangGraph flow.

### Reranking
Both retrieval paths (`vector_tool` and `rag_engine.build_context`) rerank the *entire* oversampled hybrid-search candidate pool (`search_k = top_k * retrieval_oversampling_factor`) with a local cross-encoder (`services/reranker.py`, lazy-loaded via `sentence-transformers`, default model `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` — multilingual, CPU-friendly, configurable via `RERANKER_MODEL`). `retrieval_score_threshold` is intentionally NOT applied before the cross-encoder runs — it used to filter on the raw Qdrant RRF fusion score (a rank-position signal across the dense/sparse prefetch lists, not a semantic relevance score), which silently discarded good candidates before the reranker ever saw them. The threshold only gates the cheaper fallback path: if the cross-encoder fails to load or `ENABLE_RERANKER=false`, both call sites fall back to the lexical rerank in `services/retrieval_utils.py` (`rerank_hybrid`, Jaccard token overlap blended with vector score), where the threshold still serves as a relevance floor.

### Config
All tunables are centralized in `backend/app/core/config.py` (`Settings`, a `pydantic_settings.BaseSettings` reading `.env`) and mirrored as environment variables for each service in `docker-compose.yml`. When adding a new tunable, add it in both places. Note `.env` values override the `docker-compose.yml` fallback defaults (`${VAR:-default}`), which override the Python class default — check all three when a setting doesn't seem to take effect.

LLM model choice is split by task instead of one shared model, tiered by call volume and reasoning need: `openai_model` (synthesizer + critic — quality-critical, 1-3 calls/query) > `router_model` / `cypher_model` (classification/structured generation, called every query but low reasoning need) > `contextual_retrieval_model` / `community_summary_model` (ingestion-time, called once per chunk/community — high volume, cheapest tier).

### MCP server (`mcp_server/server.py`)
A thin FastMCP wrapper that calls the backend's REST API over HTTP (not in-process) using `X-MCP-API-Key`. Exposes `search_knowledge_base`, `answer_knowledge_base`, `query_knowledge_base` (alias), `explore_graph`. Public access goes through Caddy at `/sse`; LibreChat talks to it over the internal Docker network.

## Coding conventions

- Python: 4-space indent, type hints where practical, `snake_case` for modules/functions/Celery tasks; FastAPI endpoints grouped by domain in router modules.
- TypeScript/React: function components with `PascalCase` filenames, `camelCase` variables, Tailwind utility classes (see `admin/src/components/`).

## Notes

- Backend auto-creates Postgres tables on startup when `AUTO_CREATE_TABLES=true` (dev default) — production should rely on Alembic instead.
- Do not commit `.env`, secrets, database dumps, uploaded documents, or anything under `data/`.
