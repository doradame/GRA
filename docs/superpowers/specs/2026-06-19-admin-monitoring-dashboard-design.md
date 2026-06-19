# Design: Admin Monitoring & Observability Dashboard

## Overview

Aggiungere una dashboard di monitoraggio nel pannello admin di Graph RAG Assistant per rendere visibili in tempo reale:

- lo stato e le prestazioni della pipeline di ingestion;
- le query/chat recenti con intent, tool usato, iterazioni e latenza;
- la salute dei servizi esterni (Postgres, Neo4j, Qdrant, MinIO, Redis, OpenAI);
- una stima dei token consumati e del costo.

Tutte le metriche restano in Postgres. Nessun nuovo servizio di monitoring viene introdotto.

## Goals

- Dare agli amministratori una visione d’insieme dello stato del sistema.
- Velocizzare il debug di ingestion fallite o lente.
- Mostrare quali tool dell’agente vengono usati e con quale latenza.
- Evidenziare servizi degradati o down.
- Fornire una stima dei costi LLM/embeddings.

## Non-goals

- Non si aggiunge Prometheus/Grafana o altri TSDB.
- Non si implementa alerting automatico (email/Slack).
- Non si tracciano metriche utente dettagliate (analytics).
- Non si modificano le logiche di retrieval o di ingestion, solo si arricchisce la telemetria.

## Architecture

```
┌─────────────────┐      ┌──────────────────┐      ┌─────────────────┐
│  IngestionTask  │──────▶  IngestionJob    │◀─────│  /admin/metrics │
│  (Celery)       │      │  (Postgres)      │      │  (FastAPI)      │
└─────────────────┘      └──────────────────┘      └────────┬────────┘
                                                            │
┌─────────────────┐      ┌──────────────────┐               │
│  Chat endpoint  │──────▶  QueryLog        │───────────────┤
│                 │      │  (Postgres)      │               │
└─────────────────┘      └──────────────────┘               │
                                                            ▼
┌─────────────────┐      ┌──────────────────┐      ┌─────────────────┐
│  Health service │──────▶  ServiceHealthCheck │◀───│  /admin/health  │
│                 │      │  (Postgres)      │      │                 │
└─────────────────┘      └──────────────────┘      └─────────────────┘
                                                            │
                                                            ▼
                                                   ┌─────────────────┐
                                                   │  Admin UI       │
                                                   │  (React/Vite)   │
                                                   └─────────────────┘
```

## Detailed design

### 1. Schema dati

#### 1.1 `IngestionJob` extensions

Aggiungere a `backend/app/models/models.py`:

```python
started_parsing_at: DateTime | None
completed_parsing_at: DateTime | None
started_chunking_at: DateTime | None
completed_chunking_at: DateTime | None
started_embedding_at: DateTime | None
completed_embedding_at: DateTime | None
started_vector_indexing_at: DateTime | None
completed_vector_indexing_at: DateTime | None
started_graph_indexing_at: DateTime | None
completed_graph_indexing_at: DateTime | None

chunk_count: int | None
entity_count: int | None
relation_count: int | None
input_tokens: int | None
output_tokens: int | None
cost_estimate_usd: float | None
```

I campi `error_code` e `error_message` esistono già.

#### 1.2 `QueryLog` extensions

Aggiungere a `backend/app/models/models.py`:

```python
tool_used: str | None  # vector, cypher, community, direct
iteration_count: int | None
input_tokens: int | None
output_tokens: int | None
cost_estimate_usd: float | None
```

#### 1.3 Nuova tabella `ServiceHealthCheck`

```python
class ServiceHealthCheck(Base):
    __tablename__ = "service_health_checks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    service = Column(String(64), unique=True, nullable=False, index=True)
    status = Column(String(32), nullable=False)  # ok, degraded, error
    latency_ms = Column(Integer, nullable=True)
    last_check_at = Column(DateTime, nullable=False)
    error_message = Column(Text, nullable=True)
```

Servizi tracciati: `postgres`, `neo4j`, `qdrant`, `minio`, `redis`, `openai`.

### 2. API backend

Nuovo router `backend/app/routers/admin.py`, montato in `main.py` con prefix `/api/v1/admin`.

#### 2.1 `GET /api/v1/admin/metrics`

Restituisce l’aggregazione pronta per la dashboard:

```json
{
  "documents": { "uploaded": 3, "completed": 12, "error": 1, "running": 2 },
  "recent_ingestions": [...],
  "recent_queries": [...],
  "services": [
    { "service": "neo4j", "status": "ok", "latency_ms": 12, "last_check_at": "..." }
  ],
  "api_usage": { "openai_calls_24h": 1523, "embeddings_24h": 8900 }
}
```

Tutti gli endpoint admin sono protetti da `get_current_active_admin`.

#### 2.2 `GET /api/v1/admin/metrics/ingestion`

Parametri: `limit`, `offset`.
Lista ingestion jobs con durata fasi e contatori.

#### 2.3 `GET /api/v1/admin/metrics/queries`

Parametri: `limit`, `offset`, `from`, `to`.
Lista query recenti con intent, tool, iterazioni, latenza.

#### 2.4 `GET /api/v1/admin/health`

Restituisce l’ultimo stato dei servizi. Se i dati sono più vecchi di 60 secondi, esegue un refresh sincrono con timeout corto per servizio.

#### 2.5 `POST /api/v1/admin/health/check`

Forza un health check completo e aggiorna `ServiceHealthCheck`.

### 3. Raccolta metriche

#### 3.1 Ingestion

In `services/ingestion.py`, `process_document` popola i timestamp e i contatori su `IngestionJob`:

- all’inizio/fine di ogni fase aggiorna `started_*_at` / `completed_*_at`;
- dopo chunking scrive `chunk_count`;
- durante graph indexing accumula `entity_count` e `relation_count`;
- stima token input/output con tiktoken per embedding e LLM calls;
- calcola `cost_estimate_usd` con tariffe statiche per modello, mantenute in `services/api_usage.py`.

#### 3.2 Query/chat

In `services/rag_engine.py` o `routers/chat.py`, dopo ogni risposta agente:

- popola `QueryLog.tool_used` dallo stato finale di LangGraph;
- popola `QueryLog.iteration_count` dal numero di giri critic/synthesizer;
- stima token e costo.

### 4. Health check

Nuovo modulo `backend/app/services/health.py` con `check_all_services()`:

| Servizio | Check implementativo |
|---|---|
| `postgres` | `SELECT 1` via SQLAlchemy |
| `neo4j` | Verifica connessione driver |
| `qdrant` | `client.health()` o info collezione |
| `minio` | `list_buckets()` |
| `redis` | `PING` |
| `openai` | Presenza `OPENAI_API_KEY` + `GET /models` con timeout 5s |

Ogni check:
- misura latenza in ms;
- restituisce `ok`, `degraded` (latenza > 1000 ms o check parziale), `error`;
- salva/aggiorna la riga corrispondente in `ServiceHealthCheck`.

Check OpenAI in dettaglio:
- `OPENAI_API_KEY` mancante → `error`.
- `OPENAI_API_KEY=sk-test` → `degraded` con messaggio "Demo mode".
- Chiave valida ma `GET /models` fallisce → `degraded` o `error` a seconda del tipo di errore.
- Chiave valida e risposta entro timeout → `ok`.

### 5. Admin UI

Nuovo componente `admin/src/components/SystemDashboard.tsx` con auto-refresh ogni 5 secondi.

Layout:

1. **Card riassuntive**: documenti per stato, query 24h, ingestion attive, servizi down.
2. **Stato servizi**: griglia con indicatori colorati, latenza, ultimo check, pulsante “Aggiorna ora”.
3. **Ingestion recenti**: tabella con file, fase, progresso, durata fasi, contatori, errore.
4. **Query recenti**: tabella con query, intent, tool, iterazioni, latenza.
5. **Alert ingestion fallite**: banner se ci sono documenti in stato `error`.

Navigazione: aggiungere voce “Dashboard” in `admin/src/components/Sidebar.tsx`.

API helpers in `admin/src/lib/api.ts`:
- `fetchAdminMetrics()`
- `fetchAdminHealth()`
- `forceHealthCheck()`

Si usano barre CSS per i progressi; nessuna nuova libreria di grafici.

## Testing

- Test unitario per `services/health.py` con mock dei client esterni.
- Test per l’endpoint `/admin/metrics` con dati fittizi in DB.
- Test per la raccolta timestamp/contatori in `process_document` usando `sk-test`.
- `npm run build` per verificare che la UI compili.

## Rollout

1. Aggiungere migration Alembic per i nuovi campi e tabella.
2. Deploy backend + worker.
3. Deploy admin UI.
4. Verificare che `OPENAI_API_KEY=sk-test` non rompa la dashboard.

## Decisions

- Check OpenAI: presenza chiave + `GET /models` con timeout 5s; `sk-test` produce stato `degraded`.
- Cost estimate v1: tariffe statiche in `services/api_usage.py`, sufficienti per una prima iterazione.
- `GET /admin/health` esegue refresh sincrono se i dati cached sono più vecchi di 60s, con timeout corto per servizio.
- Dashboard UI senza librerie grafiche aggiuntive; barre CSS e tabelle.
