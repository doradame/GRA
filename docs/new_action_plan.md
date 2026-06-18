# Action Plan: Evoluzione Architettura GraphRAG Ibrida

**Obiettivo:** Trasformare l'attuale pipeline di ingestion e retrieval da un sistema RAG documentale di base a un ecosistema GraphRAG agentico e scalabile, superando i limiti di estrazione parziale e migliorando la precisione del retrieval tramite vettori sparsi avanzati e navigazione topologica del grafo.

**Stato attuale (aggiornato al 18/06/2026):**
* ✅ Fase 1 completata — vettori sparsi BM25 + entity resolution fuzzy con APOC.
* ✅ Fase 2 completata — estrazione entità con GLiNER su tutti i chunk, relazioni solo via LLM.
* ✅ Fase 3 completata — orchestrazione agentica con LangGraph, Local/Global Graph Search.

---

## Fase 1: Ottimizzazione Fondamenta Dati (Vector & Graph Store) ✅ COMPLETATA

Risolta la gestione ingenua dei vettori sparsi e la frammentazione delle entità nel grafo.

### 1.1. Refactoring Vettori Sparsi (Sparse Embeddings)
* **Stato:** Completato in `services/sparse_vectors.py`.
* **Implementazione:** Algoritmo BM25-like con tokenizzazione NLTK (con fallback robusto), stopwords inglesi/italiane, e hashing BLAKE2b dei token in bucket sparsi compatibili con Qdrant.
* **Dettagli:**
    * Parametri BM25 standard: `k1=1.5`, `b=0.75`.
    * IDF calcolato sul corpus dei chunk del documento in fase di indexing.
    * Durante il retrieval, se il corpus non è disponibile, si usa solo il TF pesato.
    * Vettore normalizzato L2 prima dell'upsert in Qdrant.
* **Requisito soddisfatto:** Compatibilità mantenuta con il payload Qdrant per ricerca ibrida RRF.

### 1.2. Entity Resolution Dinamica (Fuzzy Merging)
* **Stato:** Completato in `services/entity_resolution.py` e `tasks/entity_resolution.py`.
* **Implementazione:**
    1. Task Celery `resolve_entities_task` raggruppa le entità Neo4j per tipo.
    2. Calcola gli embedding dei nomi con `embed_texts` (batch 64).
    3. Calcola la matrice di similarità del coseno.
    4. Per valori `> 0.93`, raggruppa le entità con Union-Find e le fonde tramite APOC.
* **Cypher Reference:** `CALL apoc.refactor.mergeNodes(nodes, {properties: 'combine', mergeRels: true, preserveExistingProperties: true})` preserva tutti gli archi `MENTIONS` e le proprietà.
* **Fix correlato:** `services/graph_store.py` ora normalizza `e.name` quando APOC lo combina in array dopo il merge.

---

## Fase 2: Sblocco Estrazione Grafo Completa ✅ COMPLETATA

Separata l'estrazione delle entità (NER) da quella delle relazioni per ottimizzare tempi e costi.

### 2.1. Estrazione Entità via SLM Locale
* **Stato:** Completato in `services/gliner_extraction.py` e integrato in `services/ingestion.py`.
* **Implementazione:**
    * Integrato **GLiNER** (`gliner-community/gliner_small-v2.5`) come modello NER locale nel worker Celery.
    * Le entità vengono estratte da **tutti i chunk** del documento, senza più il limite dei 48 chunk.
    * Label configurabili via `GLINER_LABELS` (default: Persona, Organizzazione, Luogo, Prodotto, Concetto, Regola, Requisito, Rischio, Data, Numero, Sistema).
    * Soglia di confidenza configurabile via `GLINER_THRESHOLD` (default `0.5`).
    * Il modello è caricato in modo lazy e cacheato nel processo worker (`_model`).
    * Le entità ottenute usano lo stesso ID canonico (`SHA256(tipo:nome)`) usato dall'estrazione legacy per garantire consistenza con il grafo.

### 2.2. Estrazione Relazioni Ottimizzata (LLM)
* **Stato:** Completato in `services/extraction.py` con la nuova funzione `extract_relations`.
* **Implementazione:**
    * L'LLM (OpenAI tramite `AsyncOpenAI`) riceve solo il testo del chunk e l'elenco delle entità già identificate da GLiNER.
    * Il prompt `RELATION_PROMPT` richiede esclusivamente di mappare le relazioni logiche tra le entità fornite.
    * Il limite di costo `MAX_RELATION_EXTRACTION_CHUNKS` (default 48, fallback su `MAX_GRAPH_EXTRACTION_CHUNKS`) si applica **solo** alle relazioni LLM, non più alle entità.
    * In modalità demo (`OPENAI_API_KEY` assente o `sk-test`) le relazioni sono vuote.
    * Il codice legacy `extract_entities_relations` è mantenuto per retrocompatibilità.

### File coinvolti Fase 2
* `backend/app/services/gliner_extraction.py` — nuovo modulo GLiNER.
* `backend/app/services/extraction.py` — `extract_relations` + prompt specializzato.
* `backend/app/services/ingestion.py` — pipeline aggiornata per usare GLiNER su tutti i chunk e LLM solo per relazioni.
* `backend/app/services/graph_store.py` — fix `name` array post-merge APOC.
* `backend/requirements.txt` — dipendenze GLiNER e pin torch.

---

## Fase 3: Orchestrazione Agentica e Retrieval Avanzato ✅ COMPLETATA

Sostituita la singola catena di query statica con un workflow decisionale in grado di instradare la domanda verso lo strumento più adatto.

### 3.1. Integrazione Framework Agentico (LangGraph)
* **Stato:** Completato in `services/agent/`.
* **Approccio:** LangGraph-light: `langgraph` gestisce stato e transizioni, i tool sono funzioni async native del progetto.
* **Componenti:**
    * **Semantic Router (`services/agent/router.py`):** Classifica l'intento in `factual`, `relational`, `summary`, `direct` via LLM con fallback euristico.
    * **Vector Tool (`services/agent/tools/vector_tool.py`):** Recupero fattuale classico via Qdrant + espansione con sottografo locale Neo4j.
    * **Text2Cypher Tool (`services/agent/tools/cypher_tool.py`):** Generazione ed esecuzione read-only di query Cypher per domande relazionali, con validazione statica e retry.
    * **Community Tool (`services/agent/tools/community_tool.py`):** Recupero riassunti `:CommunitySummary` correlati alle entità della query.
    * **Synthesizer (`services/agent/nodes.py`):** Unifica i risultati degli strumenti e genera la risposta finale con citazioni.
    * **Grafo (`services/agent/graph.py`):** Assemblaggio del grafo LangGraph con routing condizionale.
* **Integrazione:** `services/rag_engine.py::chat_completion` ora invoca `agent_graph.ainvoke` mantenendo la stessa firma e retrocompatibilità dell'endpoint `/api/v1/chat/completions`.

### 3.2. Local Graph Search (Iniezione di Contesto Topologico)
* **Stato:** Completato in `services/agent/tools/vector_tool.py` e `services/graph_store.py`.
* **Implementazione:** Dopo il recupero ibrido dai chunk, i `chunk_id` vengono usati per estrarre il sottografo locale:
    ```cypher
    MATCH (c:Chunk)-[:MENTIONS]->(e:Entity)-[r]-(e2:Entity)
    WHERE c.id IN $chunk_ids
    RETURN e.name AS source, type(r) AS rel_type, e2.name AS target
    LIMIT 200
    ```
* **Iniezione:** I fatti vengono deduplicati, limitati a `AGENT_MAX_GRAPH_FACTS` e serializzati come `"X --[rel]--> Y"` nel contesto del prompt.

### 3.3. Global Graph Summarization (Community Detection)
* **Stato:** Completato in `services/community_detection.py` e `tasks/community_detection.py`.
* **Implementazione:**
    * Algoritmo **Louvain** via libreria Python `python-louvain` (GDS non disponibile in Neo4j Community Edition).
    * Task Celery `community_detection_task` eseguibile on-demand dall'endpoint admin.
    * Per ogni community vengono estratte entità e relazioni interne, generato un riassunto con LLM e salvato come nodo `:CommunitySummary` con relazioni `BELONGS_TO_COMMUNITY`.
    * Endpoint admin: `POST /api/v1/graph/community-detection` e `GET /api/v1/graph/community-summaries`.

### File coinvolti Fase 3
* `backend/app/services/agent/state.py` — modelli e `AgentState`.
* `backend/app/services/agent/router.py` — semantic router.
* `backend/app/services/agent/nodes.py` — `direct_answer` e `synthesizer`.
* `backend/app/services/agent/tools/vector_tool.py` — Vector Tool + local graph expansion.
* `backend/app/services/agent/tools/cypher_tool.py` — Text2Cypher Tool.
* `backend/app/services/agent/tools/community_tool.py` — Community Tool.
* `backend/app/services/agent/graph.py` — grafo LangGraph.
* `backend/app/services/community_detection.py` — logica community detection.
* `backend/app/services/retrieval_utils.py` — utility di retrieval condivise.
* `backend/app/services/rag_engine.py` — integrazione agente.
* `backend/app/services/graph_store.py` — vincolo `CommunitySummary` e metodi di supporto.
* `backend/app/tasks/community_detection.py` — task Celery.
* `backend/app/core/config.py` — configurazioni agente e community detection.
* `backend/app/core/celery_app.py` — include il nuovo task.
* `backend/app/routers/graph.py` — endpoint admin.
* `backend/app/models/schemas.py` — schemi response community.
* `backend/requirements.txt` — `langgraph`, `networkx`, `python-louvain`.
* `backend/docker-compose.yml` — variabili d'ambiente agente/community.
* `backend/tests/test_agent_router.py`, `test_cypher_tool.py`, `test_vector_tool.py`, `test_community_detection.py`.

---
