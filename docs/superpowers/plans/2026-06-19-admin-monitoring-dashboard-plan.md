# Admin Monitoring Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aggiungere una dashboard admin con metriche di ingestion, query, health check servizi e stima costi, senza introdurre nuovi servizi.

**Architecture:** Le metriche restano in Postgres (`IngestionJob`, `QueryLog`, nuova `ServiceHealthCheck`). Un nuovo router FastAPI `/api/v1/admin` espone aggregazioni e health check. La UI sostituisce la dashboard esistente con un componente che mostra card, tabelle e stato servizi.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Postgres, React + Vite + TypeScript + Tailwind, pytest.

---

## File structure

| File | Responsibility |
|---|---|
| `backend/alembic/versions/..._add_monitoring_fields.py` | Migration per nuovi campi e tabella |
| `backend/app/models/models.py` | Estensioni ORM IngestionJob/QueryLog + ServiceHealthCheck |
| `backend/app/models/schemas.py` | Schemi Pydantic IngestionJobOut/QueryLogOut + AdminMetricsOut/ServiceHealthOut |
| `backend/app/services/health.py` | Health check di Postgres, Neo4j, Qdrant, MinIO, Redis, OpenAI |
| `backend/app/services/api_usage.py` | Cost estimate helper + contatori esistenti |
| `backend/app/services/ingestion.py` | Popola timestamp/contatori/token su IngestionJob |
| `backend/app/services/query_log.py` | Popola tool_used/iteration_count/token su QueryLog |
| `backend/app/routers/admin.py` | Endpoint `/admin/metrics`, `/admin/health`, `/admin/metrics/ingestion`, `/admin/metrics/queries` |
| `backend/app/main.py` | Registrazione router admin |
| `backend/tests/test_health.py` | Test unitari health service |
| `backend/tests/test_admin_metrics.py` | Test endpoint admin metrics |
| `admin/src/lib/api.ts` | Helpers `fetchAdminMetrics`, `fetchAdminHealth`, `forceHealthCheck`, tipi TS |
| `admin/src/components/Dashboard.tsx` | Nuova dashboard con card, tabelle, health |
| `admin/src/App.tsx` | Usa `Dashboard` al posto del blocco inline dashboard |

---

## Task 1: Migration Alembic

**Files:**
- Create: `backend/alembic/versions/20260619_add_monitoring_fields.py`

- [ ] **Step 1: Genera il file migration**

```bash
cd backend
source .venv/bin/activate
alembic revision -m "add monitoring fields and service health check"
```

- [ ] **Step 2: Scrivi la migration**

Sostituisci il contenuto generato con:

```python
"""add monitoring fields and service health check

Revision ID: 20260619_add_monitoring_fields
Revises: <lascia quello generato da alembic>
Create Date: <lascia quello generato da alembic>

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
# Lascia revision e down_revision generati da Alembic; non modificare revision.
# Se down_revision è None e ci sono migration precedenti, aggiornalo con la head precedente.


def upgrade() -> None:
    # IngestionJob extensions
    op.add_column('ingestion_jobs', sa.Column('started_parsing_at', sa.DateTime(), nullable=True))
    op.add_column('ingestion_jobs', sa.Column('completed_parsing_at', sa.DateTime(), nullable=True))
    op.add_column('ingestion_jobs', sa.Column('started_chunking_at', sa.DateTime(), nullable=True))
    op.add_column('ingestion_jobs', sa.Column('completed_chunking_at', sa.DateTime(), nullable=True))
    op.add_column('ingestion_jobs', sa.Column('started_embedding_at', sa.DateTime(), nullable=True))
    op.add_column('ingestion_jobs', sa.Column('completed_embedding_at', sa.DateTime(), nullable=True))
    op.add_column('ingestion_jobs', sa.Column('started_vector_indexing_at', sa.DateTime(), nullable=True))
    op.add_column('ingestion_jobs', sa.Column('completed_vector_indexing_at', sa.DateTime(), nullable=True))
    op.add_column('ingestion_jobs', sa.Column('started_graph_indexing_at', sa.DateTime(), nullable=True))
    op.add_column('ingestion_jobs', sa.Column('completed_graph_indexing_at', sa.DateTime(), nullable=True))
    op.add_column('ingestion_jobs', sa.Column('chunk_count', sa.Integer(), nullable=True))
    op.add_column('ingestion_jobs', sa.Column('entity_count', sa.Integer(), nullable=True))
    op.add_column('ingestion_jobs', sa.Column('relation_count', sa.Integer(), nullable=True))
    op.add_column('ingestion_jobs', sa.Column('input_tokens', sa.Integer(), nullable=True))
    op.add_column('ingestion_jobs', sa.Column('output_tokens', sa.Integer(), nullable=True))
    op.add_column('ingestion_jobs', sa.Column('cost_estimate_usd', sa.Float(), nullable=True))

    # QueryLog extensions
    op.add_column('query_logs', sa.Column('tool_used', sa.String(length=32), nullable=True))
    op.add_column('query_logs', sa.Column('iteration_count', sa.Integer(), nullable=True))
    op.add_column('query_logs', sa.Column('input_tokens', sa.Integer(), nullable=True))
    op.add_column('query_logs', sa.Column('output_tokens', sa.Integer(), nullable=True))
    op.add_column('query_logs', sa.Column('cost_estimate_usd', sa.Float(), nullable=True))

    # ServiceHealthCheck
    op.create_table(
        'service_health_checks',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('service', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('last_check_at', sa.DateTime(), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('service'),
    )
    op.create_index(op.f('ix_service_health_checks_service'), 'service_health_checks', ['service'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_service_health_checks_service'), table_name='service_health_checks')
    op.drop_table('service_health_checks')

    op.drop_column('query_logs', 'cost_estimate_usd')
    op.drop_column('query_logs', 'output_tokens')
    op.drop_column('query_logs', 'input_tokens')
    op.drop_column('query_logs', 'iteration_count')
    op.drop_column('query_logs', 'tool_used')

    op.drop_column('ingestion_jobs', 'cost_estimate_usd')
    op.drop_column('ingestion_jobs', 'output_tokens')
    op.drop_column('ingestion_jobs', 'input_tokens')
    op.drop_column('ingestion_jobs', 'relation_count')
    op.drop_column('ingestion_jobs', 'entity_count')
    op.drop_column('ingestion_jobs', 'chunk_count')
    op.drop_column('ingestion_jobs', 'completed_graph_indexing_at')
    op.drop_column('ingestion_jobs', 'started_graph_indexing_at')
    op.drop_column('ingestion_jobs', 'completed_vector_indexing_at')
    op.drop_column('ingestion_jobs', 'started_vector_indexing_at')
    op.drop_column('ingestion_jobs', 'completed_embedding_at')
    op.drop_column('ingestion_jobs', 'started_embedding_at')
    op.drop_column('ingestion_jobs', 'completed_chunking_at')
    op.drop_column('ingestion_jobs', 'started_chunking_at')
    op.drop_column('ingestion_jobs', 'completed_parsing_at')
    op.drop_column('ingestion_jobs', 'started_parsing_at')
```

- [ ] **Step 3: Verifica migration**

```bash
cd backend
alembic upgrade head
alembic current
```

Expected output: versione `20260619_add_monitoring_fields`.

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/20260619_add_monitoring_fields.py
git commit -m "chore: add migration for monitoring fields and service health check"
```

---

## Task 2: Estendere i modelli SQLAlchemy

**Files:**
- Modify: `backend/app/models/models.py`

- [ ] **Step 1: Aggiungi campi a `IngestionJob`**

Dopo i campi esistenti di `IngestionJob`, aggiungi:

```python
    started_parsing_at = Column(DateTime, nullable=True)
    completed_parsing_at = Column(DateTime, nullable=True)
    started_chunking_at = Column(DateTime, nullable=True)
    completed_chunking_at = Column(DateTime, nullable=True)
    started_embedding_at = Column(DateTime, nullable=True)
    completed_embedding_at = Column(DateTime, nullable=True)
    started_vector_indexing_at = Column(DateTime, nullable=True)
    completed_vector_indexing_at = Column(DateTime, nullable=True)
    started_graph_indexing_at = Column(DateTime, nullable=True)
    completed_graph_indexing_at = Column(DateTime, nullable=True)

    chunk_count = Column(Integer, nullable=True)
    entity_count = Column(Integer, nullable=True)
    relation_count = Column(Integer, nullable=True)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    cost_estimate_usd = Column(Float, nullable=True)
```

- [ ] **Step 2: Aggiungi campi a `QueryLog`**

Dopo `latency_ms`, aggiungi:

```python
    tool_used = Column(String(32), nullable=True)
    iteration_count = Column(Integer, nullable=True)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    cost_estimate_usd = Column(Float, nullable=True)
```

- [ ] **Step 3: Aggiungi `ServiceHealthCheck`**

Dopo `IngestionJob`, aggiungi:

```python
class ServiceHealthCheck(Base):
    __tablename__ = "service_health_checks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    service = Column(String(64), unique=True, nullable=False, index=True)
    status = Column(String(32), nullable=False)
    latency_ms = Column(Integer, nullable=True)
    last_check_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    error_message = Column(Text, nullable=True)
```

- [ ] **Step 4: Verifica import e avvio backend**

```bash
cd backend
python -c "from app.models.models import IngestionJob, QueryLog, ServiceHealthCheck; print('OK')"
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/models.py
git commit -m "feat(models): add monitoring fields and ServiceHealthCheck"
```

---

## Task 3: Estendere gli schemi Pydantic

**Files:**
- Modify: `backend/app/models/schemas.py`

- [ ] **Step 1: Estendi `IngestionJobOut`**

Aggiungi dentro `IngestionJobOut`:

```python
    started_parsing_at: Optional[datetime] = None
    completed_parsing_at: Optional[datetime] = None
    started_chunking_at: Optional[datetime] = None
    completed_chunking_at: Optional[datetime] = None
    started_embedding_at: Optional[datetime] = None
    completed_embedding_at: Optional[datetime] = None
    started_vector_indexing_at: Optional[datetime] = None
    completed_vector_indexing_at: Optional[datetime] = None
    started_graph_indexing_at: Optional[datetime] = None
    completed_graph_indexing_at: Optional[datetime] = None

    chunk_count: Optional[int] = None
    entity_count: Optional[int] = None
    relation_count: Optional[int] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost_estimate_usd: Optional[float] = None
```

- [ ] **Step 2: Estendi `QueryLogOut`**

Aggiungi dentro `QueryLogOut`:

```python
    tool_used: Optional[str] = None
    iteration_count: Optional[int] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost_estimate_usd: Optional[float] = None
```

- [ ] **Step 3: Aggiungi schemi admin**

In fondo a `schemas.py`, aggiungi:

```python
# Admin monitoring
class ServiceHealthOut(BaseModel):
    id: str
    service: str
    status: str
    latency_ms: Optional[int] = None
    last_check_at: datetime
    error_message: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

    @field_validator("id", mode="before")
    @classmethod
    def _uuid_to_str(cls, v):
        return str(v)


class AdminMetricsOut(BaseModel):
    documents: dict
    recent_ingestions: List[IngestionJobOut]
    recent_queries: List[QueryLogOut]
    services: List[ServiceHealthOut]
    api_usage: dict
```

Nota: `IngestionJobList` e `QueryLogList` esistono già in `schemas.py`; non duplicarli.

- [ ] **Step 4: Verifica import**

```bash
cd backend
python -c "from app.models.schemas import AdminMetricsOut, ServiceHealthOut; print('OK')"
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/schemas.py
git commit -m "feat(schemas): add admin monitoring schemas"
```

---

## Task 4: Implementare il servizio di health check

**Files:**
- Create: `backend/app/services/health.py`
- Create: `backend/tests/test_health.py`

- [ ] **Step 1: Scrivi `health.py`**

```python
import time
import logging
from datetime import datetime, timedelta
from typing import Awaitable

from app.core.config import get_settings
from app.core.database import engine
from app.services.storage import storage
from app.services.vector_store import vector_store
from app.services.graph_store import graph_store

settings = get_settings()
logger = logging.getLogger(__name__)

DEGRADED_LATENCY_MS = 1000
TIMEOUT_SECONDS = 5


async def _check_postgres() -> dict:
    start = time.perf_counter()
    try:
        async with engine.connect() as conn:
            await conn.execute("SELECT 1")
        latency = int((time.perf_counter() - start) * 1000)
        return {"status": "ok", "latency_ms": latency}
    except Exception as e:
        logger.exception("[health] Postgres check failed")
        return {"status": "error", "latency_ms": None, "error_message": str(e)[:500]}


async def _check_neo4j() -> dict:
    start = time.perf_counter()
    try:
        graph_store.check_connection()
        latency = int((time.perf_counter() - start) * 1000)
        return {"status": "ok", "latency_ms": latency}
    except Exception as e:
        logger.exception("[health] Neo4j check failed")
        return {"status": "error", "latency_ms": None, "error_message": str(e)[:500]}


async def _check_qdrant() -> dict:
    start = time.perf_counter()
    try:
        vector_store.health()
        latency = int((time.perf_counter() - start) * 1000)
        return {"status": "ok", "latency_ms": latency}
    except Exception as e:
        logger.exception("[health] Qdrant check failed")
        return {"status": "error", "latency_ms": None, "error_message": str(e)[:500]}


async def _check_minio() -> dict:
    start = time.perf_counter()
    try:
        storage.client.list_buckets()
        latency = int((time.perf_counter() - start) * 1000)
        return {"status": "ok", "latency_ms": latency}
    except Exception as e:
        logger.exception("[health] MinIO check failed")
        return {"status": "error", "latency_ms": None, "error_message": str(e)[:500]}


async def _check_redis() -> dict:
    start = time.perf_counter()
    try:
        import redis
        r = redis.from_url(settings.celery_broker_url, socket_connect_timeout=TIMEOUT_SECONDS)
        r.ping()
        latency = int((time.perf_counter() - start) * 1000)
        return {"status": "ok", "latency_ms": latency}
    except Exception as e:
        logger.exception("[health] Redis check failed")
        return {"status": "error", "latency_ms": None, "error_message": str(e)[:500]}


async def _check_openai() -> dict:
    if not settings.openai_api_key:
        return {"status": "error", "latency_ms": None, "error_message": "OPENAI_API_KEY not set"}
    if settings.openai_api_key == "sk-test":
        return {"status": "degraded", "latency_ms": None, "error_message": "Demo mode (sk-test)"}

    start = time.perf_counter()
    try:
        import httpx
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            )
            response.raise_for_status()
        latency = int((time.perf_counter() - start) * 1000)
        return {"status": "ok", "latency_ms": latency}
    except Exception as e:
        logger.exception("[health] OpenAI check failed")
        return {"status": "degraded", "latency_ms": None, "error_message": str(e)[:500]}


async def check_all_services() -> dict[str, dict]:
    """Run all health checks concurrently and return a map service -> result."""
    checks = {
        "postgres": _check_postgres(),
        "neo4j": _check_neo4j(),
        "qdrant": _check_qdrant(),
        "minio": _check_minio(),
        "redis": _check_redis(),
        "openai": _check_openai(),
    }
    results = {}
    for name, coro in checks.items():
        try:
            result = await coro
        except Exception as e:
            logger.exception("[health] Unexpected error checking %s", name)
            result = {"status": "error", "latency_ms": None, "error_message": str(e)[:500]}
        if result.get("latency_ms", 0) > DEGRADED_LATENCY_MS and result["status"] == "ok":
            result["status"] = "degraded"
        results[name] = result
    return results
```

Nota: richiede che `graph_store` e `vector_store` esportino metodi `check_connection()` e `health()`. Se non esistono, Task 4.5 li aggiunge.

- [ ] **Step 2: Aggiungi `check_connection` a `graph_store.py`**

In `backend/app/services/graph_store.py`, aggiungi un metodo alla classe/driver:

```python
def check_connection(self) -> None:
    with self.driver.session() as session:
        session.run("RETURN 1")
```

- [ ] **Step 3: Aggiungi `health` a `vector_store.py`**

In `backend/app/services/vector_store.py`, aggiungi:

```python
def health(self) -> None:
    self.client.health()
```

- [ ] **Step 4: Scrivi il test `test_health.py`**

```python
import pytest
from unittest.mock import patch, MagicMock
from app.services.health import check_all_services


@pytest.mark.asyncio
async def test_check_all_services_maps_names():
    with patch("app.services.health.engine") as mock_engine, \
         patch("app.services.health.graph_store") as mock_graph, \
         patch("app.services.health.vector_store") as mock_vector, \
         patch("app.services.health.storage") as mock_storage, \
         patch("app.services.health.redis") as mock_redis, \
         patch("app.services.health.httpx") as mock_httpx, \
         patch("app.services.health.get_settings") as mock_settings:

        mock_settings.return_value.openai_api_key = "sk-test"
        mock_settings.return_value.celery_broker_url = "redis://localhost:6379/0"

        mock_conn = MagicMock()
        mock_engine.connect.return_value.__aenter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__aexit__ = MagicMock(return_value=False)

        results = await check_all_services()

        assert set(results.keys()) == {"postgres", "neo4j", "qdrant", "minio", "redis", "openai"}
        assert results["openai"]["status"] == "degraded"
```

- [ ] **Step 5: Esegui il test**

```bash
cd backend
pytest tests/test_health.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/health.py backend/app/services/graph_store.py backend/app/services/vector_store.py backend/tests/test_health.py
git commit -m "feat(health): add service health checks"
```

---

## Task 5: Cost estimate helper

**Files:**
- Modify: `backend/app/services/api_usage.py`

- [ ] **Step 1: Aggiungi tariffe e helper**

Aggiungi in cima al file:

```python
from datetime import datetime, timedelta

# Tariffe approssimative per 1M token (input / output).
# Override possibile via env in futuro.
MODEL_COSTS: dict[str, dict[str, float]] = {
    "gpt-5.4": {"input": 2.50, "output": 10.00},
    "gpt-5.4-mini": {"input": 0.15, "output": 0.60},
    "gpt-5.4-nano": {"input": 0.075, "output": 0.30},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "text-embedding-3-large": {"input": 0.13, "output": 0.0},
    "text-embedding-3-small": {"input": 0.02, "output": 0.0},
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int = 0) -> float:
    """Return estimated cost in USD for a given model and token counts."""
    rates = MODEL_COSTS.get(model, MODEL_COSTS.get("gpt-4o-mini", {"input": 0.15, "output": 0.60}))
    input_cost = (input_tokens / 1_000_000) * rates["input"]
    output_cost = (output_tokens / 1_000_000) * rates["output"]
    return round(input_cost + output_cost, 6)
```

- [ ] **Step 2: Aggiungi test unitario**

Crea `backend/tests/test_api_usage.py`:

```python
from app.services.api_usage import estimate_cost_usd


def test_estimate_cost_gpt4o_mini():
    cost = estimate_cost_usd("gpt-4o-mini", 1_000_000, 500_000)
    assert cost == pytest.approx(0.45, 0.01)


def test_estimate_cost_embedding():
    cost = estimate_cost_usd("text-embedding-3-large", 1_000_000, 0)
    assert cost == pytest.approx(0.13, 0.01)
```

- [ ] **Step 3: Esegui i test**

```bash
cd backend
pytest tests/test_api_usage.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/api_usage.py backend/tests/test_api_usage.py
git commit -m "feat(api_usage): add cost estimate helper"
```

---

## Task 6: Raccolta metriche ingestion

**Files:**
- Modify: `backend/app/services/ingestion.py`

- [ ] **Step 1: Importa helper cost e tiktoken**

Aggiungi in alto:

```python
from app.services.api_usage import estimate_cost_usd
```

`tiktoken` è già importato.

- [ ] **Step 2: Aggiungi helper per contare token**

Dopo `_token_count`, aggiungi:

```python
def _count_tokens_for_model(texts: list[str], model: str) -> int:
    return sum(_token_count(t, model) for t in texts)
```

- [ ] **Step 3: Popola timestamp nelle fasi**

In `process_document`, subito dopo `job = await _get_or_create_job(...)`, aggiungi:

```python
from datetime import datetime
```

(se non già importato)

Poi, prima di ogni `_set_document_status`, imposta il timestamp di inizio; dopo, quello di fine. Esempio per parsing:

Prima di:
```python
await _set_document_status(db, doc, STATUS_PARSING, job=job)
```
aggiungi:
```python
job.started_parsing_at = datetime.utcnow()
```

Dopo l’estrazione del testo e `await db.commit()`, aggiungi:
```python
job.completed_parsing_at = datetime.utcnow()
```

Ripeti per chunking, embedding, vector_indexing, graph_indexing usando i nomi dei campi corrispondenti.

- [ ] **Step 4: Popola contatori e token**

Dopo `chunks = chunk_text(text)`:

```python
job.chunk_count = len(chunks)
```

Dopo `embeddings = await embed_texts(embedding_inputs)`:

```python
job.input_tokens = _count_tokens_for_model(embedding_inputs, settings.embedding_model)
job.output_tokens = 0  # embeddings non hanno output tokens
job.cost_estimate_usd = (job.cost_estimate_usd or 0.0) + estimate_cost_usd(
    settings.embedding_model, job.input_tokens, 0
)
```

Durante graph indexing, inizializza:

```python
job.entity_count = 0
job.relation_count = 0
```

Dopo ogni chunk, accumula:

```python
job.entity_count += len(entities)
job.relation_count += len(relations)
```

Per il costo LLM di estrazione relazioni e contextual retrieval, stima i token degli input LLM e accumula:

Dopo `generate_chunk_contexts` (se abilitato):

```python
if settings.enable_rich_contextual_retrieval:
    ctx_tokens = _count_tokens_for_model(llm_contexts, settings.contextual_retrieval_model)
    job.input_tokens = (job.input_tokens or 0) + ctx_tokens
    job.output_tokens = (job.output_tokens or 0) + sum(_token_count(c) for c in llm_contexts)
    job.cost_estimate_usd = (job.cost_estimate_usd or 0.0) + estimate_cost_usd(
        settings.contextual_retrieval_model, ctx_tokens, sum(_token_count(c) for c in llm_contexts)
    )
```

Per `extract_relations`, stima in modo simile. Dopo il loop di graph indexing:

```python
relation_input_tokens = _count_tokens_for_model(chunks, settings.openai_model)
relation_output_tokens = sum(_token_count(str(r)) for r in relations)  # approssimato
job.input_tokens = (job.input_tokens or 0) + relation_input_tokens
job.output_tokens = (job.output_tokens or 0) + relation_output_tokens
job.cost_estimate_usd = (job.cost_estimate_usd or 0.0) + estimate_cost_usd(
    settings.openai_model, relation_input_tokens, relation_output_tokens
)
```

- [ ] **Step 5: Verifica con demo mode**

```bash
cd backend
OPENAI_API_KEY=sk-test pytest tests/test_ingestion.py -v -k test_process
```

Se non esistono test di ingestion, creane uno minimale che verifica che i campi siano popolati.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ingestion.py
git commit -m "feat(ingestion): record phase timestamps, counters, tokens and cost"
```

---

## Task 6.5: Tracciare tool e iterazioni nell'agente

**Files:**
- Modify: `backend/app/services/agent/state.py`
- Modify: `backend/app/services/agent/graph.py`

- [ ] **Step 1: Estendi `AgentState`**

In `state.py`, aggiungi:

```python
tool_used: Annotated[list[str], operator.add] = []  # nomi dei tool usati
iterations: Annotated[list[dict], operator.add] = []  # storico iteration critic
```

- [ ] **Step 2: Popola `tool_used` in `graph.py`**

Dopo il routing, aggiungi il nome del tool nello stato. Esempio nella funzione di routing:

```python
def route_after_router(state: AgentState) -> str:
    intent = state["intent"]
    if intent == "direct":
        state["tool_used"] = ["direct"]
        return "synthesizer"
    if intent == "relational":
        state["tool_used"] = ["cypher"]
        return "cypher_tool"
    if intent == "summary":
        state["tool_used"] = ["community"]
        return "community_tool"
    state["tool_used"] = ["vector"]
    return "vector_tool"
```

Adatta i nomi alle funzioni reali del grafo.

- [ ] **Step 3: Popola `iterations` in `graph.py`**

Nel loop del critic, appendi un dict per ogni iterazione:

```python
state["iterations"] = state.get("iterations", []) + [{
    "iteration": len(state.get("iterations", [])) + 1,
    "refined_query": state.get("user_query", ""),
}]
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/agent/state.py backend/app/services/agent/graph.py
git commit -m "feat(agent): track tool_used and iterations in AgentState"
```

---

## Task 7: Raccolta metriche query

**Files:**
- Modify: `backend/app/services/query_log.py`
- Modify: `backend/app/services/rag_engine.py` (o `backend/app/routers/chat.py`)

- [ ] **Step 1: Estendi `record_query_log`**

Aggiungi parametri:

```python
async def record_query_log(
    *,
    source: str,
    query: str,
    user_id: str | None = None,
    user_email: str | None = None,
    intent: str | None = None,
    reasoning: str | None = None,
    answer: str | None = None,
    citation_count: int = 0,
    error: str | None = None,
    latency_ms: int | None = None,
    tool_used: str | None = None,
    iteration_count: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_estimate_usd: float | None = None,
) -> None:
```

E aggiungi i campi nella creazione di `QueryLog`.

- [ ] **Step 2: Popola metriche nel router chat**

In `backend/app/routers/chat.py`, dove viene chiamato `record_query_log`, passa i nuovi valori. Esempio:

```python
await record_query_log(
    source="api",
    query=user_message,
    user_id=str(current_user.id),
    user_email=current_user.email,
    intent=final_state.get("intent"),
    reasoning=final_state.get("reasoning"),
    answer=answer_text,
    citation_count=len(citations),
    latency_ms=int((end - start) * 1000),
    tool_used=final_state.get("tool_used"),
    iteration_count=len(final_state.get("iterations", [])),
    input_tokens=input_tokens,
    output_tokens=output_tokens,
    cost_estimate_usd=cost_estimate_usd,
)
```

I nomi esatti dipendono dallo `AgentState`. Se `tool_used`/`iteration_count` non esistono, aggiungerli a `agent/state.py` e popolarli in `agent/nodes.py`.

- [ ] **Step 3: Calcola token e costo per query**

Dopo avere la risposta:

```python
from app.services.api_usage import estimate_cost_usd

input_tokens = _token_count(user_message + context_text, settings.openai_model)
output_tokens = _token_count(answer_text, settings.openai_model)
cost_estimate_usd = estimate_cost_usd(settings.openai_model, input_tokens, output_tokens)
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/query_log.py backend/app/routers/chat.py
git commit -m "feat(query): record tool, iterations, tokens and cost in QueryLog"
```

---

## Task 8: Router admin

**Files:**
- Create: `backend/app/routers/admin.py`
- Create: `backend/tests/test_admin_metrics.py`

- [ ] **Step 1: Scrivi `admin.py`**

```python
import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc

from app.core.auth import get_current_active_admin
from app.core.database import get_db
from app.models.models import User, Document, IngestionJob, QueryLog, ServiceHealthCheck
from app.models.schemas import (
    AdminMetricsOut,
    IngestionJobList,
    QueryLogList,
    ServiceHealthOut,
)
from app.services.health import check_all_services
from app.services.api_usage import get_api_usage

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/metrics", response_model=AdminMetricsOut)
async def get_admin_metrics(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_admin),
):
    # documents by status
    status_counts = {}
    for status in ["uploaded", "parsing", "chunking", "embedding", "vector_indexing", "graph_indexing", "completed", "error"]:
        result = await db.execute(select(func.count(Document.id)).where(Document.status == status))
        status_counts[status] = result.scalar() or 0

    # recent ingestions
    ingestions_result = await db.execute(
        select(IngestionJob).order_by(desc(IngestionJob.created_at)).limit(20)
    )
    ingestions = ingestions_result.scalars().all()

    # recent queries
    queries_result = await db.execute(
        select(QueryLog).order_by(desc(QueryLog.created_at)).limit(20)
    )
    queries = queries_result.scalars().all()

    # services
    services_result = await db.execute(select(ServiceHealthCheck))
    services = services_result.scalars().all()

    # api usage
    api_usage = get_api_usage()

    return AdminMetricsOut(
        documents=status_counts,
        recent_ingestions=list(ingestions),
        recent_queries=list(queries),
        services=services,
        api_usage=api_usage,
    )


@router.get("/metrics/ingestion", response_model=IngestionJobList)
async def list_ingestion_metrics(
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_admin),
):
    safe_limit = min(max(limit, 1), 200)
    result = await db.execute(
        select(IngestionJob).order_by(desc(IngestionJob.created_at)).offset(offset).limit(safe_limit)
    )
    items = result.scalars().all()
    total_result = await db.execute(select(func.count(IngestionJob.id)))
    total = total_result.scalar() or 0
    return IngestionJobList(items=list(items), total=total)


@router.get("/metrics/queries", response_model=QueryLogList)
async def list_query_metrics(
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_admin),
):
    safe_limit = min(max(limit, 1), 200)
    result = await db.execute(
        select(QueryLog).order_by(desc(QueryLog.created_at)).offset(offset).limit(safe_limit)
    )
    items = result.scalars().all()
    total_result = await db.execute(select(func.count(QueryLog.id)))
    total = total_result.scalar() or 0
    return QueryLogList(items=list(items), total=total)


@router.get("/health", response_model=list[ServiceHealthOut])
async def get_health_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_admin),
):
    result = await db.execute(select(ServiceHealthCheck))
    services = result.scalars().all()
    # Refresh if stale (>60s)
    if not services or all((datetime.utcnow() - s.last_check_at).total_seconds() > 60 for s in services):
        return await _refresh_health(db)
    return services


@router.post("/health/check", response_model=list[ServiceHealthOut])
async def force_health_check(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_admin),
):
    return await _refresh_health(db)


async def _refresh_health(db: AsyncSession) -> list[ServiceHealthCheck]:
    results = await check_all_services()
    now = datetime.utcnow()
    updated = []
    for service, data in results.items():
        result = await db.execute(select(ServiceHealthCheck).where(ServiceHealthCheck.service == service))
        row = result.scalar_one_or_none()
        if row is None:
            row = ServiceHealthCheck(service=service)
            db.add(row)
        row.status = data["status"]
        row.latency_ms = data.get("latency_ms")
        row.last_check_at = now
        row.error_message = data.get("error_message")
        updated.append(row)
    await db.commit()
    for row in updated:
        await db.refresh(row)
    return updated
```

- [ ] **Step 2: Registra il router in `main.py`**

Aggiungi import:

```python
from app.routers import auth, documents, chat, graph, kb, logs, admin
```

E montalo:

```python
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"])
```

- [ ] **Step 3: Scrivi test `test_admin_metrics.py`**

```python
import pytest
from httpx import AsyncClient
from app.main import app
from app.core.database import AsyncSessionLocal
from app.models.models import User, ServiceHealthCheck


@pytest.mark.asyncio
async def test_admin_metrics_requires_admin():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/api/v1/admin/metrics")
    assert response.status_code == 401
```

Aggiungi test più dettagliati con utente admin se necessario.

- [ ] **Step 4: Esegui i test**

```bash
cd backend
pytest tests/test_admin_metrics.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/admin.py backend/app/main.py backend/tests/test_admin_metrics.py
git commit -m "feat(admin): add admin metrics and health endpoints"
```

---

## Task 9: API helpers e tipi admin UI

**Files:**
- Modify: `admin/src/lib/api.ts`

- [ ] **Step 1: Aggiungi tipi**

Dopo `QueryLog`, aggiungi:

```typescript
export interface ServiceHealth {
  service: string
  status: 'ok' | 'degraded' | 'error'
  latency_ms: number | null
  last_check_at: string
  error_message: string | null
}

export interface IngestionMetrics {
  items: IngestionJob[]
  total: number
}

export interface QueryMetrics {
  items: QueryLog[]
  total: number
}

export interface AdminMetrics {
  documents: Record<string, number>
  recent_ingestions: IngestionJob[]
  recent_queries: QueryLog[]
  services: ServiceHealth[]
  api_usage: APIUsage
}
```

- [ ] **Step 2: Aggiungi helpers**

In fondo al file:

```typescript
export async function fetchAdminMetrics() {
  const res = await api.get('/admin/metrics')
  return res.data as AdminMetrics
}

export async function fetchAdminHealth() {
  const res = await api.get('/admin/health')
  return res.data as ServiceHealth[]
}

export async function forceHealthCheck() {
  const res = await api.post('/admin/health/check')
  return res.data as ServiceHealth[]
}
```

- [ ] **Step 3: Commit**

```bash
git add admin/src/lib/api.ts
git commit -m "feat(admin-ui): add admin metrics api helpers and types"
```

---

## Task 10: Componente Dashboard

**Files:**
- Create: `admin/src/components/Dashboard.tsx`
- Modify: `admin/src/App.tsx`

- [ ] **Step 1: Crea `Dashboard.tsx`**

```tsx
import { useEffect, useState, useCallback } from 'react'
import KnowledgeBaseInfo from './KnowledgeBaseInfo'
import ApiUsage from './ApiUsage'
import {
  fetchAdminMetrics,
  fetchAdminHealth,
  forceHealthCheck,
  AdminMetrics,
  ServiceHealth,
} from '../lib/api'

interface Props {
  onTokenInvalid: () => void
  refreshCounter: number
}

export default function Dashboard({ onTokenInvalid, refreshCounter }: Props) {
  const [metrics, setMetrics] = useState<AdminMetrics | null>(null)
  const [health, setHealth] = useState<ServiceHealth[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    try {
      const [m, h] = await Promise.all([fetchAdminMetrics(), fetchAdminHealth()])
      setMetrics(m)
      setHealth(h)
    } catch (err: any) {
      if (err.response?.status === 401) onTokenInvalid()
    } finally {
      setLoading(false)
    }
  }, [onTokenInvalid])

  useEffect(() => {
    load()
    const interval = setInterval(load, 5000)
    return () => clearInterval(interval)
  }, [load, refreshCounter])

  const handleRefreshHealth = async () => {
    setLoading(true)
    try {
      const h = await forceHealthCheck()
      setHealth(h)
    } finally {
      setLoading(false)
    }
  }

  const serviceColor = (status: string) => {
    switch (status) {
      case 'ok':
        return 'bg-green-500'
      case 'degraded':
        return 'bg-yellow-500'
      case 'error':
        return 'bg-red-500'
      default:
        return 'bg-gray-400'
    }
  }

  if (loading && !metrics) return <div className="p-6 text-slate-500">Caricamento dashboard...</div>

  const errorCount = metrics?.documents.error ?? 0

  return (
    <div className="space-y-6">
      {errorCount > 0 && (
        <div className="bg-red-50 border border-red-200 text-red-800 px-4 py-3 rounded-lg">
          Attenzione: {errorCount} documento/i in errore.
        </div>
      )}

      <KnowledgeBaseInfo onTokenInvalid={onTokenInvalid} />

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard label="Documenti completati" value={metrics?.documents.completed ?? 0} />
        <MetricCard label="Ingestion attive" value={
          (metrics?.documents.parsing ?? 0) +
          (metrics?.documents.chunking ?? 0) +
          (metrics?.documents.embedding ?? 0) +
          (metrics?.documents.vector_indexing ?? 0) +
          (metrics?.documents.graph_indexing ?? 0)
        } />
        <MetricCard label="Query 24h" value={metrics?.recent_queries.length ?? 0} />
        <MetricCard label="Servizi down" value={health.filter((s) => s.status === 'error').length} />
      </div>

      <ApiUsage onTokenInvalid={onTokenInvalid} />

      <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-200">
        <div className="flex justify-between items-center mb-4">
          <h3 className="font-semibold text-slate-800">Stato servizi</h3>
          <button
            onClick={handleRefreshHealth}
            className="text-sm bg-slate-100 text-slate-700 px-3 py-1 rounded hover:bg-slate-200"
          >
            Aggiorna ora
          </button>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          {health.map((svc) => (
            <div key={svc.service} className="border rounded-lg p-3">
              <div className="flex items-center gap-2">
                <div className={`w-3 h-3 rounded-full ${serviceColor(svc.status)}`} />
                <span className="font-medium capitalize">{svc.service}</span>
              </div>
              <div className="text-sm text-slate-500 mt-1">
                {svc.latency_ms !== null ? `${svc.latency_ms} ms` : 'N/A'}
              </div>
              {svc.error_message && (
                <div className="text-xs text-red-600 mt-1">{svc.error_message}</div>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-200">
        <h3 className="font-semibold text-slate-800 mb-4">Ingestion recenti</h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left">
              <th className="pb-2">Fase</th>
              <th className="pb-2">Progresso</th>
              <th className="pb-2">Chunk</th>
              <th className="pb-2">Entità</th>
              <th className="pb-2">Relazioni</th>
              <th className="pb-2">Costo</th>
            </tr>
          </thead>
          <tbody>
            {(metrics?.recent_ingestions ?? []).map((job) => (
              <tr key={job.id} className="border-b last:border-0">
                <td className="py-2">{job.phase}</td>
                <td className="py-2">{job.progress}%</td>
                <td className="py-2">{job.chunk_count ?? '-'}</td>
                <td className="py-2">{job.entity_count ?? '-'}</td>
                <td className="py-2">{job.relation_count ?? '-'}</td>
                <td className="py-2">${job.cost_estimate_usd?.toFixed(4) ?? '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-200">
        <h3 className="font-semibold text-slate-800 mb-4">Query recenti</h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left">
              <th className="pb-2">Query</th>
              <th className="pb-2">Intent</th>
              <th className="pb-2">Tool</th>
              <th className="pb-2">Iterazioni</th>
              <th className="pb-2">Latenza</th>
            </tr>
          </thead>
          <tbody>
            {(metrics?.recent_queries ?? []).map((q) => (
              <tr key={q.id} className="border-b last:border-0">
                <td className="py-2 max-w-xs truncate">{q.query}</td>
                <td className="py-2">{q.intent ?? '-'}</td>
                <td className="py-2">{q.tool_used ?? '-'}</td>
                <td className="py-2">{q.iteration_count ?? '-'}</td>
                <td className="py-2">{q.latency_ms ? `${q.latency_ms} ms` : '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function MetricCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-white p-4 rounded-xl shadow-sm border border-slate-200">
      <div className="text-2xl font-semibold text-slate-800">{value}</div>
      <div className="text-sm text-slate-500">{label}</div>
    </div>
  )
}
```

- [ ] **Step 2: Aggiorna `App.tsx`**

Importa:

```typescript
import Dashboard from './components/Dashboard'
```

Sostituisci il blocco dashboard:

```tsx
          {page === 'dashboard' && (
            <Dashboard
              key={refreshCounter}
              refreshCounter={refreshCounter}
              onTokenInvalid={handleTokenInvalid}
            />
          )}
```

Rimuovi gli import di `KnowledgeBaseInfo` e `ApiUsage` se non usati altrove.

- [ ] **Step 3: Verifica build**

```bash
cd admin
npm run build
```

Expected: build success, zero TypeScript errors.

- [ ] **Step 4: Commit**

```bash
git add admin/src/components/Dashboard.tsx admin/src/App.tsx
git commit -m "feat(admin-ui): add monitoring dashboard component"
```

---

## Task 11: Test end-to-end e verifica regressione

**Files:**
- None (solo comandi)

- [ ] **Step 1: Avvia lo stack in demo mode**

```bash
cp .env.example .env
# modifica OPENAI_API_KEY=sk-test
docker compose up -d
```

- [ ] **Step 2: Crea utente admin e carica un documento**

```bash
curl -X POST https://api.matamune.4nk.eu/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"secret"}'

# rendilo admin (via DB o endpoint esistente se presente)
# carica un PDF dal pannello admin
```

- [ ] **Step 3: Verifica endpoint admin**

```bash
curl -H "Authorization: Bearer <token>" https://api.matamune.4nk.eu/api/v1/admin/metrics | jq
curl -H "Authorization: Bearer <token>" https://api.matamune.4nk.eu/api/v1/admin/health | jq
```

Expected: JSON valido con dati.

- [ ] **Step 4: Verifica UI**

Apri https://admin.matamune.4nk.eu, accedi, controlla che la Dashboard mostri card, stato servizi, ingestion e query.

- [ ] **Step 5: Esegui test backend**

```bash
cd backend
pytest
```

Expected: tutti i test passano.

- [ ] **Step 6: Commit eventuali fix**

```bash
git add -A
git commit -m "fix: address monitoring dashboard regressions"
```

---

## Self-review checklist

- [ ] **Spec coverage:** ogni sezione del design doc ha almeno un task.
- [ ] **Placeholder scan:** nessun TBD/TODO/"implement later" nel piano.
- [ ] **Type consistency:** nomi campi (`tool_used`, `iteration_count`, `cost_estimate_usd`) coerenti tra modelli, schemi, API e UI.
- [ ] **Regressione:** il piano mantiene `KnowledgeBaseInfo` e `ApiUsage` esistenti nella nuova dashboard.
- [ ] **Test:** ogni task backend ha un test; UI ha `npm run build`.

---

## Execution handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-19-admin-monitoring-dashboard-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
