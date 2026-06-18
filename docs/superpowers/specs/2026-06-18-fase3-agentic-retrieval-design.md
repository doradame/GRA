# Design: Fase 3 — Orchestrazione Agentica e Retrieval Avanzato

**Progetto:** `graph-rag-assistant`  
**Data:** 2026-06-18  
**Stato:** Design completo, pronto per l'implementazione  
**Scopo:** Questo documento è auto-contenuto e descrive nel dettaglio l'architettura, i componenti, i flussi e i file coinvolti dalla Fase 3. Deve essere usato come unica fonte di verità per l'implementazione dopo un eventuale clear del contesto.

---

## 1. Contesto e stato attuale

Il sistema è uno stack Graph RAG self-hosted composto da:

- **Backend:** FastAPI (`backend/app/`)
- **Worker:** Celery per task di ingestion ed entity resolution
- **Vector store:** Qdrant (dense + sparse BM25-like)
- **Graph store:** Neo4j (Community Edition 5.x)
- **Object storage:** MinIO
- **Database relazionale:** PostgreSQL
- **LLM:** OpenAI via `AsyncOpenAI` (modello default `gpt-4o-mini`)
- **NER locale:** GLiNER (`gliner-community/gliner_small-v2.5`)

### Fase 1 completata
- Vettori sparsi BM25-like in `services/sparse_vectors.py`.
- Entity resolution fuzzy in `services/entity_resolution.py` + task Celery `tasks/entity_resolution.py`.
- Fix post-merge APOC in `services/graph_store.py` (`_stringify_name`).

### Fase 2 completata
- Estrazione entità con GLiNER su **tutti i chunk** (`services/gliner_extraction.py`).
- Estrazione relazioni solo con LLM sui primi `MAX_RELATION_EXTRACTION_CHUNKS` chunk (`services/extraction.py::extract_relations`).
- Pipeline di ingestion aggiornata in `services/ingestion.py`.

### Punto di partenza per la Fase 3
Il retrieval attuale è implementato in `services/rag_engine.py`:
- `build_context()` esegue retrieval ibrido da Qdrant.
- Espande il contesto con un'esplorazione grafo molto basilare (`explore_entity` su entità estraette dalla query).
- `chat_completion()` costruisce il messaggio di sistema con il contesto e chiama OpenAI.
- Lo streaming è supportato.

L'obiettivo della Fase 3 è trasformare questa catena statica in un **workflow agentico decisionale** in grado di instradare la domanda verso lo strumento più adatto, arricchire il retrieval con contesto topologico e rispondere a domande di sintesi ad alto livello tramite community detection.

---

## 2. Obiettivi della Fase 3

1. **Semantic Router:** classificare l'intento della query e decidere se serve:
   - recupero fattuale vettoriale (Vector Tool),
   - query relazionale sul grafo (Text2Cypher Tool),
   - sintesi ad alto livello sulle community (Community Tool),
   - risposta diretta / saluto (bypass LLM).

2. **Vector Tool arricchito:** eseguire hybrid search su Qdrant e poi arricchire i chunk con il sottografo locale delle entità menzionate.

3. **Text2Cypher Tool:** generare ed eseguire query Cypher su Neo4j per domande relazionali esplicite (es. "Quali sistemi dipendono dal Firewall X?").

4. **Community Tool (Global Graph Summarization):** usare algoritmi di community detection (Leiden/Louvain via GDS o implementazione Python) per identificare cluster di entità, generare riassunti con LLM e salvarli come nodi `:CommunitySummary` in Neo4j.

5. **Synthesizer finale:** unificare i risultati degli strumenti in una risposta naturale con citazioni.

6. **Mantenere retrocompatibilità:** l'endpoint `/api/v1/chat/completions` deve continuare a funzionare; l'agente sostituisce internamente `rag_engine.chat_completion`.

---

## 3. Approccio architetturale scelto

### Opzioni considerate

1. **LangGraph puro:** usare `langgraph` come framework di orchestrazione completo.
   - *Pro:* state machine robusta, integrazione con LangChain, debug visuale.
   - *Contro:* dipendenza pesante, API in rapida evoluzione, potenziale overkill per 4 nodi.

2. **State machine custom:** implementare un orchestratore async con classi `State`, `Node`, `Edge`.
   - *Pro:* controllo totale, nessuna dipendenza extra, adatto al codebase esistente.
   - *Contro:* più codice boilerplate da mantenere.

3. **LangGraph-light (scelto):** usare `langgraph` solo per la gestione dello stato e le transizioni, implementando i tool come funzioni/async native del progetto.
   - *Pro:* bilancia struttura e leggerezza; riusa i servizi esistenti; state machine esplicita.
   - *Contro:* richiede di apprendere le convenzioni LangGraph.

### Decisione
Adottare l'**approccio 3 (LangGraph-light)**. Il grafo dell'agente sarà composto da pochi nodi ben definiti; ogni nodo è una funzione Python async che opera su uno stato condiviso (`AgentState`). I tool non saranno wrapper LangChain, ma chiamate dirette ai servizi interni (`vector_store`, `graph_store`, LLM via `AsyncOpenAI`).

---

## 4. Architettura dell'agente

### 4.1 Stato condiviso (`AgentState`)

```python
class AgentState(TypedDict):
    # Input
    messages: List[Dict[str, str]]       # Storia completa della conversazione
    user_query: str                       # Ultimo messaggio utente normalizzato
    user_id: str | None                   # Per filtraggio retrieval per utente

    # Decisione del router
    intent: Literal[
        "factual",      # domanda fattuale -> Vector Tool
        "relational",   # domanda relazionale -> Text2Cypher Tool
        "summary",      # domanda di sintesi -> Community Tool
        "direct",       # saluto/domanda generica -> risposta diretta
    ]
    reasoning: str                        # Spiegazione del router (per debug)

    # Risultati degli strumenti
    vector_results: VectorToolResult | None
    cypher_results: CypherToolResult | None
    community_results: CommunityToolResult | None

    # Contesto finale e risposta
    context: str                          # Contesto testuale unito da iniettare nel prompt
    citations: List[Citation]
    answer: str | None
    error: str | None
```

### 4.2 Grafo dei nodi

```
[START]
   │
   ▼
[semantic_router] ──(intent=direct)──► [direct_answer] ──► [END]
   │
   ├──(intent=factual)────► [vector_tool] ──┐
   │                                         │
   ├──(intent=relational)─► [text2cypher_tool]─┤
   │                                         │
   └──(intent=summary)────► [community_tool]──┤
                                              ▼
                                       [synthesizer]
                                              │
                                              ▼
                                           [END]
```

### 4.3 Nodi

| Nodo | File | Responsabilità |
|------|------|----------------|
| `semantic_router` | `services/agent/router.py` | Classifica l'intento, popola `intent` e `reasoning`. |
| `direct_answer` | `services/agent/nodes.py` | Genera risposta cortesia senza retrieval. |
| `vector_tool` | `services/agent/tools/vector_tool.py` | Hybrid search + local graph expansion. |
| `text2cypher_tool` | `services/agent/tools/cypher_tool.py` | Genera ed esegue Cypher, verifica risultato. |
| `community_tool` | `services/agent/tools/community_tool.py` | Recupera riassunti delle community. |
| `synthesizer` | `services/agent/nodes.py` | Unifica i risultati e chiama l'LLM finale. |

---

## 5. Componenti dettagliati

### 5.1 Semantic Router

**File:** `services/agent/router.py`

**Input:** `user_query` + opzionalmente `messages`.

**Implementazione:**
- Prima strategia: LLM con prompt di classificazione strutturato e `response_format={"type": "json_object"}`.
- Fallback: euristica rapida basata su keyword (es. "quali", "elenca", "dipende", "collegato" per relational; "sommario", "temi principali" per summary).
- Il prompt deve includere esempi di classificazione in italiano.

**Output JSON:**
```json
{
  "intent": "factual|relational|summary|direct",
  "reasoning": "breve spiegazione"
}
```

**Regole di classificazione:**
- `direct`: saluti, domande sull'assistente, domande senza riferimento ai documenti.
- `factual`: domande il cui contenuto è probabilmente in uno o più chunk ("Cosa dice il documento X riguardo Y?").
- `relational`: domande su connessioni, dipendenze, relazioni tra entità ("Quali sistemi sono bloccati dal firewall X?").
- `summary`: domande di sintesi o panoramica ("Quali sono le tematiche principali?", "Riassumi gli argomenti trattati").

---

### 5.2 Vector Tool

**File:** `services/agent/tools/vector_tool.py`

**Responsabilità:**
1. Eseguire hybrid search su Qdrant come in `rag_engine.build_context`.
2. Estrarre i `chunk_id` dai top-K risultati.
3. Interrogare Neo4j per il sottografo locale:
   ```cypher
   MATCH (c:Chunk)-[:MENTIONS]->(e:Entity)-[r]-(e2:Entity)
   WHERE c.id IN $chunk_ids
   RETURN e.name AS source, type(r) AS rel_type, e2.name AS target
   LIMIT 200
   ```
4. Serializzare le relazioni in testo naturale.
5. Restituire contesto testuale + citazioni.

**Output (`VectorToolResult`):**
```python
class VectorToolResult(BaseModel):
    chunks: List[dict]              # payload dei chunk recuperati
    local_graph_facts: List[str]    # es. "X --[dipende_da]--> Y"
    context: str
    citations: List[Citation]
```

**Deduplicazione:**
- Deduplicare fatti del grafo per `(source.lower(), rel_type.lower(), target.lower())`.
- Limitare a max 20 fatti per non saturare il contesto.

---

### 5.3 Text2Cypher Tool

**File:** `services/agent/tools/cypher_tool.py`

**Responsabilità:**
1. Generare una query Cypher a partire dalla domanda utente e dallo schema del grafo.
2. Eseguire la query su Neo4j in read-only (solo `MATCH`/`RETURN`/`WITH`/`CALL`; rifiutare write).
3. Se la query fallisce, effettuare **un retry** con l'errore come feedback.
4. Restituire i risultati in forma testuale.

**Schema del grafo da fornire al prompt:**
```text
Nodi:
- :Document {id, filename, content_type, user_id}
- :Chunk {id, text, index, user_id}
- :Entity {id, name, type, normalized_name}
- :CommunitySummary {id, summary, created_at}  (aggiunto in Fase 3)

Relazioni:
- (Chunk)-[:BELONGS_TO]->(Document)
- (Chunk)-[:MENTIONS]->(Entity)
- (Entity)-[:<TIPO_DINAMICO>]->(Entity)
```

**Prompt di generazione Cypher:**
- Specificare che le query devono essere read-only.
- Suggerire l'uso di `toLower(e.name) CONTAINS toLower($term)` per match fuzzy sui nomi.
- Usare `LIMIT` per evitare risultati enormi.
- Restituire JSON: `{"cypher": "...", "parameters": {"term": "..."}}`.

**Validazione della query:**
- Rifiutare token di write: `CREATE`, `DELETE`, `DETACH`, `SET`, `REMOVE`, `MERGE`, `DROP`.
- Permettere solo `MATCH`, `RETURN`, `WITH`, `UNWIND`, `CALL`, `WHERE`, `LIMIT`, `OPTIONAL`, `ORDER BY`, `COUNT`, `COLLECT`.

**Output (`CypherToolResult`):**
```python
class CypherToolResult(BaseModel):
    cypher: str
    results: List[dict]
    summary: str          # Riassunto testuale generato dall'LLM
    error: str | None
```

---

### 5.4 Community Tool (Global Graph Summarization)

**File:**
- `services/agent/tools/community_tool.py` — recupero dei riassunti.
- `services/community_detection.py` — logica di community detection + generazione riassunti.
- `tasks/community_detection.py` — task Celery per eseguire il job in background.

#### 5.4.1 Generazione dei riassunti (job periodico)

**Algoritmo di community detection:**
- Neo4j GDS non è disponibile in Community Edition. Usare una libreria Python:
  - **Preferita:** `python-louvain` (`community` package) o `igraph` per Louvain.
  - **Alternativa:** `networkx` + `cdlib` se servono altri algoritmi.
- Costruire il grafo delle entità leggendo relazioni `(Entity)-[r]->(Entity)` da Neo4j.
- Eseguire community detection sul grafo non diretto.
- Per ogni community, estrarre le entità e le relazioni interne.
- Generare un riassunto con LLM tramite prompt dedicato.
- Salvare/aggiornare nodo `:CommunitySummary`:
  ```cypher
  MERGE (cs:CommunitySummary {community_id: $community_id})
  SET cs.summary = $summary,
      cs.entity_count = $entity_count,
      cs.relation_count = $relation_count,
      cs.updated_at = datetime()
  WITH cs
  UNWIND $entity_ids AS entity_id
  MATCH (e:Entity {id: entity_id})
  MERGE (e)-[:BELONGS_TO_COMMUNITY]->(cs)
  ```

**Output (`CommunitySummary` model):**
```python
class CommunitySummary(BaseModel):
    community_id: str
    summary: str
    entity_count: int
    relation_count: int
    updated_at: datetime
```

#### 5.4.2 Recupero in fase di query

Il Community Tool, quando chiamato:
1. Esegue una hybrid search su Qdrant come il Vector Tool per identificare chunk/entità rilevanti.
2. Estrae le entità menzionate dai chunk top.
3. Cerca i `:CommunitySummary` collegati a quelle entità.
4. Restituisce i riassunti come contesto.

**Output (`CommunityToolResult`):**
```python
class CommunityToolResult(BaseModel):
    summaries: List[str]
    community_ids: List[str]
    context: str
```

---

### 5.5 Synthesizer

**File:** `services/agent/nodes.py`

**Responsabilità:**
1. Raccogliere i risultati dallo stato (`vector_results`, `cypher_results`, `community_results`).
2. Costruire il contesto finale concatenando i vari pezzi con separatori.
3. Chiamare l'LLM con il `SYSTEM_PROMPT` esistente + contesto.
4. Restituire `answer` e `citations`.

**Gestione streaming:**
- Il synthesizer può restituire una `AsyncGenerator` per lo streaming.
- In modalità streaming, LangGraph non è naturalmente adatto; in tal caso si può eseguire solo il routing e i tool in modo sincrono, poi restituire il generatore per la generazione finale.
- **Decisione:** per semplicità, la prima implementazione della Fase 3 può supportare solo risposte non-streaming. Lo streaming verrà aggiunto in un secondo momento con un wrapper che materializza i risultati degli strumenti e poi streama la risposta LLM.

---

## 6. Modelli dati

### 6.1 Neo4j

Aggiungere il nodo `:CommunitySummary`:

```cypher
CREATE CONSTRAINT community_summary_id IF NOT EXISTS
FOR (cs:CommunitySummary) REQUIRE cs.id IS UNIQUE;
```

Proprietà:
- `id` (stringa, UUID o hash della community)
- `summary` (stringa, riassunto testuale)
- `entity_count` (int)
- `relation_count` (int)
- `created_at` (datetime)
- `updated_at` (datetime)

Relazione:
- `(Entity)-[:BELONGS_TO_COMMUNITY]->(CommunitySummary)`

### 6.2 PostgreSQL (opzionale)

Se si preferisce tracciare i job di community detection, aggiungere una tabella `CommunityDetectionJob` oppure riutilizzare il pattern di `IngestionJob`. Per la prima versione, è sufficiente tracciare tramite log Celery.

---

## 7. API

### 7.1 Endpoint esistente da modificare

`POST /api/v1/chat/completions` in `routers/chat.py`:
- Sostituire `services.rag_engine.chat_completion` con il nuovo agente.
- Mantenere la stessa firma di input/output.
- Supportare `stream` come ora; per la prima versione, in caso di `stream=True`, eseguire agente in modo sincrono e poi streamare la risposta finale (vedi sezione 5.5).

### 7.2 Nuovi endpoint admin (opzionali ma consigliati)

`POST /api/v1/graph/community-detection` (admin only):
- Accetta `algorithm` (default `louvain`), `resolution` opzionale.
- Lancia task Celery `community_detection_task`.
- Ritorna `{"task_id": "...", "status": "queued"}`.

`GET /api/v1/graph/community-summaries`:
- Lista dei riassunti delle community (con paginazione opzionale).

---

## 8. Configurazione

Aggiungere in `core/config.py` e in `docker-compose.yml`:

```python
# Agent
agent_max_iterations: int = 3              # max iterazioni di tool loop (utile per future estensioni)
agent_cypher_max_retries: int = 1
agent_max_graph_facts: int = 20           # max fatti del sottografo locale
agent_max_community_summaries: int = 5

# Community detection
community_detection_algorithm: str = "louvain"   # o "leiden"
community_detection_resolution: float = 1.0
community_summary_model: str = "gpt-4o-mini"     # modello per riassunti community
community_summary_max_entities: int = 50         # max entità per community da inviare all'LLM
```

Variabili d'ambiente corrispondenti:
- `AGENT_MAX_ITERATIONS`
- `AGENT_CYPHER_MAX_RETRIES`
- `AGENT_MAX_GRAPH_FACTS`
- `AGENT_MAX_COMMUNITY_SUMMARIES`
- `COMMUNITY_DETECTION_ALGORITHM`
- `COMMUNITY_DETECTION_RESOLUTION`
- `COMMUNITY_SUMMARY_MODEL`
- `COMMUNITY_SUMMARY_MAX_ENTITIES`

---

## 9. Flussi di esempio

### 9.1 Domanda fattuale

**Utente:** "Quali requisiti sono previsti per l'accesso ai dati?"

1. Router classifica `intent=factual`.
2. Vector Tool esegue hybrid search, trova i chunk rilevanti.
3. Local Graph Search estrae relazioni tra entità nei chunk (es. "accesso ai dati --[richiede]--> autenticazione").
4. Synthesizer costruisce il contesto e genera la risposta con citazioni.

### 9.2 Domanda relazionale

**Utente:** "Quali sistemi dipendono dal Firewall DMZ?"

1. Router classifica `intent=relational`.
2. Text2Cypher Tool genera:
   ```cypher
   MATCH (fw:Entity)-[:DIPENDE_DA|BLOCCATO_DA|CONNESSO_A]-(sys:Entity)
   WHERE toLower(fw.name) CONTAINS 'firewall dmz'
   RETURN sys.name AS sistema
   LIMIT 20
   ```
3. Esegue la query su Neo4j.
4. Synthesizer riassume i risultati.

### 9.3 Domanda di sintesi

**Utente:** "Quali sono le tematiche principali del documento?"

1. Router classifica `intent=summary`.
2. Community Tool recupera i `:CommunitySummary` collegati alle entità più rilevanti della query.
3. Synthesizer genera una risposta panoramica.

---

## 10. Task Celery

### 10.1 Nuovo task: `community_detection_task`

**File:** `tasks/community_detection.py`

```python
@shared_task(bind=True, max_retries=3)
def community_detection_task(self, algorithm: str = "louvain", resolution: float = 1.0):
    result = asyncio.run(run_community_detection(algorithm=algorithm, resolution=resolution))
    return result
```

### 10.2 Schedulazione (opzionale)

Aggiungere in `celery_app.py` la configurazione Celery Beat per eseguire `community_detection_task` periodicamente (es. ogni notte o ogni settimana). Per semplicità iniziale, esporre solo l'endpoint admin per avviarlo manualmente.

---

## 11. Strategia di test

### 11.1 Unit test

- `tests/test_agent_router.py`: test di classificazione con query di esempio (usare mock LLM).
- `tests/test_cypher_tool.py`: test di validazione query (permetti solo read) e generazione mock.
- `tests/test_vector_tool.py`: test di local graph expansion con mock Neo4j.
- `tests/test_community_detection.py`: test dell'algoritmo su piccolo grafo NetworkX.

### 11.2 Integration test

- `tests/test_agent_e2e.py`: con `RUN_AGENT_E2E=1`, eseguire l'agente end-to-end con Neo4j/Qdrant up e una chiave OpenAI di test (`sk-test` per testare il flusso senza costi).

### 11.3 Manual QA

- Domande fattuali, relazionali e di sintesi su documenti noti.
- Verificare che le citazioni siano presenti e corrette.
- Verificare che Cypher malevolo venga rifiutato.

---

## 12. Rischi e mitigazioni

| Rischio | Mitigazione |
|---------|-------------|
| LangGraph introduce complessità | Usare solo le primitive base (`StateGraph`, `END`, `add_node`, `add_conditional_edges`). |
| Query Cypher generate pericolose | Validazione statica dei token; esecuzione con utente Neo4j a bassi privilegi; read-only. |
| Community detection su grafo grande è lenta | Limitare a entità con almeno N relazioni; eseguire in background; caching riassunti. |
| Riassunti community diventano obsoleti | Aggiornare solo quando cambia il grafo (dopo ingestion) o tramite schedule periodico. |
| Aumento costi LLM | Limitare `MAX_RELATION_EXTRACTION_CHUNKS` e `agent_max_community_summaries`; usare modello economico per riassunti. |
| Streaming complicato con LangGraph | Prima implementazione non-streaming; poi wrapper separato per stream. |

---

## 13. Dipendenze

Aggiungere a `requirements.txt`:

```text
langgraph>=0.2.0
networkx>=3.0
python-louvain>=0.16
```

Valutare:
- `igraph` come alternativa più performante per Louvain su grafi grandi.
- `cdlib` se si vuole supportare più algoritmi (Leiden, ecc.).

---

## 14. File da creare/modificare

### Nuovi file

| File | Descrizione |
|------|-------------|
| `services/agent/__init__.py` | Package agente. |
| `services/agent/state.py` | Definizione `AgentState` e modelli Pydantic. |
| `services/agent/router.py` | Semantic router. |
| `services/agent/nodes.py` | Nodi `direct_answer` e `synthesizer`. |
| `services/agent/tools/__init__.py` | Package tool. |
| `services/agent/tools/vector_tool.py` | Vector Tool + local graph expansion. |
| `services/agent/tools/cypher_tool.py` | Text2Cypher Tool. |
| `services/agent/tools/community_tool.py` | Community Tool. |
| `services/agent/graph.py` | Costruzione e compilazione del grafo LangGraph. |
| `services/community_detection.py` | Logica community detection + generazione riassunti. |
| `tasks/community_detection.py` | Task Celery per community detection. |
| `tests/test_agent_router.py` | Test router. |
| `tests/test_cypher_tool.py` | Test Cypher tool. |
| `tests/test_vector_tool.py` | Test vector tool. |
| `tests/test_community_detection.py` | Test community detection. |

### File da modificare

| File | Modifica |
|------|----------|
| `services/rag_engine.py` | Sostituire `chat_completion` e `build_context` con chiamata all'agente; mantenere funzioni legacy come wrapper se utile. |
| `routers/chat.py` | Nessuna modifica se `rag_engine.chat_completion` mantiene la stessa firma. |
| `routers/graph.py` | Aggiungere endpoint community detection e community summaries. |
| `services/graph_store.py` | Aggiungere metodi per `explore_local_subgraph`, `get_community_summaries`, `add_community_summary`, vincolo `CommunitySummary.id`. |
| `core/config.py` | Aggiungere parametri agente e community detection. |
| `core/celery_app.py` | Includere `app.tasks.community_detection`. |
| `requirements.txt` | Aggiungere `langgraph`, `networkx`, `python-louvain`. |
| `docker-compose.yml` | Aggiungere variabili d'ambiente per agente e community detection. |

---

## 15. Checklist implementazione

1. [ ] Aggiungere dipendenze a `requirements.txt` e rebuild container.
2. [ ] Implementare `AgentState` e modelli in `services/agent/state.py`.
3. [ ] Implementare `semantic_router` con prompt e fallback euristico.
4. [ ] Implementare `VectorTool` con local graph expansion.
5. [ ] Implementare `CypherTool` con validazione read-only e retry.
6. [ ] Implementare `CommunityDetection` service + task Celery.
7. [ ] Implementare `CommunityTool` per recuperare riassunti.
8. [ ] Implementare `synthesizer` e `direct_answer`.
9. [ ] Assemblare il grafo LangGraph in `services/agent/graph.py`.
10. [ ] Integrare l'agente in `services/rag_engine.py::chat_completion`.
11. [ ] Aggiungere vincolo Neo4j per `CommunitySummary`.
12. [ ] Aggiungere endpoint admin per community detection.
13. [ ] Aggiungere configurazioni in `core/config.py` e `docker-compose.yml`.
14. [ ] Scrivere test unitari e integration test.
15. [ ] Eseguire `pytest` locale e in Docker.
16. [ ] Aggiornare `docs/new_action_plan.md` segnando Fase 3 come completata.

---

## 16. Note per lo sviluppo post-clear-context

- **Non modificare** `services/gliner_extraction.py`, `services/entity_resolution.py`, `services/sparse_vectors.py` se non per bugfix.
- **Mantenere** l'endpoint `/api/v1/chat/completions` retrocompatibile: deve accettare lo stesso `ChatRequest` e restituire lo stesso formato OpenAI-like.
- **Testare sempre** in Docker con `docker compose run --rm -e PYTHONPATH=/app backend pytest -q` dopo aver montato `./backend/tests:/app/tests` in `docker-compose.yml`.
- **Per il router:** se il costo LLM è un problema, iniziare con la classificazione euristica e aggiungere LLM solo se necessario.
- **Per Cypher:** la validazione statica è essenziale; non esporre mai Cypher generato senza filtro.
- **Per community detection:** iniziare con `python-louvain`; passare a `igraph` solo se il grafo supera decine di migliaia di entità.

---

## 17. Riferimenti rapidi

- Documentazione progetto:
  - `docs/new_action_plan.md`
  - `docs/ingestion_pipeline.md`
  - `docs/ingestion-pipeline-dettagliato.md`
- File chiave esistenti:
  - `services/rag_engine.py`
  - `services/graph_store.py`
  - `services/vector_store.py`
  - `services/extraction.py`
  - `services/gliner_extraction.py`
  - `routers/chat.py`
  - `routers/graph.py`
