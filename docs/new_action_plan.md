# Action Plan: Evoluzione Architettura GraphRAG Ibrida

**Obiettivo:** Trasformare l'attuale pipeline di ingestion e retrieval da un sistema RAG documentale di base a un ecosistema GraphRAG agentico e scalabile, superando i limiti di estrazione parziale e migliorando la precisione del retrieval tramite vettori sparsi avanzati e navigazione topologica del grafo.

**Stato attuale (aggiornato al 19/06/2026):**
* ✅ Fase 1 completata — vettori sparsi BM25 + entity resolution fuzzy con APOC.
* ✅ Fase 2 completata — estrazione entità con GLiNER su tutti i chunk, relazioni solo via LLM.
* ✅ Fase 3 completata — orchestrazione agentica con LangGraph, Local/Global Graph Search.
* ✅ Fase 4 completata — BM25 globale, community detection gerarchica, loop critic/auto-correzione, parsing layout-aware, fix soglia pre-rerank.
* ✅ Fase 5 completata — modelli LLM aggiornati a GPT-5.4, differenziati per funzione; fix bug troncamento input del critic.

---

## Fase 1: Ottimizzazione Fondamenta Dati (Vector & Graph Store) ✅ COMPLETATA

Risolta la gestione ingenua dei vettori sparsi e la frammentazione delle entità nel grafo.

### 1.1. Refactoring Vettori Sparsi (Sparse Embeddings)
* **Stato:** Completato in `services/sparse_vectors.py`. **Superato dalla Fase 4** (vedi sotto): l'hashing BLAKE2b in bucket e l'IDF calcolato solo sul corpus del singolo documento sono stati sostituiti da un BM25 reale con vocabolario stabile e statistiche corpus-wide.
* **Implementazione originale:** Algoritmo BM25-like con tokenizzazione NLTK (con fallback robusto), stopwords inglesi/italiane, e hashing BLAKE2b dei token in bucket sparsi compatibili con Qdrant.
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
* **Stato:** Completato in `services/community_detection.py` e `tasks/community_detection.py`. **Estesa nella Fase 4** con un secondo livello gerarchico (`root`).
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

## Fase 4: BM25 Globale, Gerarchia delle Community, Loop Critic e Fix Retrieval ✅ COMPLETATA

Obiettivo: portare la qualità del retrieval e del ragionamento agentico oltre i limiti delle Fasi 1-3, con interventi mirati e verificabili su CPU (nessun modello vision/multimodale).

### 4.1. BM25 reale e globale (corpus-wide)
* **Stato:** Completato in `services/sparse_vectors.py` (riscritto) e `services/sparse_corpus_stats.py` (nuovo).
* **Problema risolto:** Il vecchio algoritmo hashava i termini in bucket (BLAKE2b) e calcolava IDF/lunghezza media solo sul corpus del singolo documento in fase di indexing — niente di stabile a query-time, e collisioni di bucket non distinguibili.
* **Implementazione:**
    * Vocabolario stabile in Postgres (`sparse_terms`: term → id intero permanente, mai ri-assegnato — Qdrant referenzia questi id come indici del vettore sparso).
    * Statistiche BM25 (`bm25:vocab`, `bm25:df`, `bm25:total_chunks`, `bm25:total_tokens`) calcolate sull'intero corpus indicizzato, cacheate in Redis per letture a query-time senza sessione DB.
    * Ogni `Document` salva il proprio contributo (`sparse_term_counts`, `sparse_total_tokens`) per poterlo sottrarre/ri-applicare in modo pulito su delete/reindex (`subtract_document_contribution`, `apply_document_delta`).
* **Migrazione:** `backend/alembic/versions/20260619_0008_sparse_bm25_global_stats.py`.

### 4.2. Community detection gerarchica (leaf + root)
* **Stato:** Completato in `services/community_detection.py`.
* **Implementazione:** Oltre al livello `leaf` (grana fine, `community_louvain.best_partition`), viene calcolato un livello `root` dal dendrogramma completo di Louvain (`generate_dendrogram` + livello più alto) — l'intero grafo collassato in poche community ampie, per riassunti "globali" senza dipendere da quali chunk il retrieval vettoriale trova per primo. `community_tool` privilegia i riassunti `root` per le domande di overview, con fallback al vecchio percorso (vector search → entità menzionate → community `leaf`) solo se la community detection non è mai stata eseguita.
* **Rebuild completo ad ogni run:** la numerazione delle community di Louvain non è stabile tra run, quindi ogni esecuzione cancella (`DETACH DELETE`) tutti i `CommunitySummary` precedenti invece di fare solo pruning incrementale.
* **Limite osservato in produzione:** su grafi sufficientemente frammentati, il livello `root` può coincidere esattamente col `leaf` (il dendrogramma di Louvain ha un solo livello reale) — il fallback è gestito correttamente nel codice, ma non produce in questo caso il beneficio di "poche community ampie" che era l'obiettivo originale.

### 4.3. Loop agentico di auto-correzione (critic)
* **Stato:** Completato in `services/agent/nodes.py` (`critic_node`) e `services/agent/graph.py`.
* **Implementazione:** Dopo il `synthesizer`, un nodo `critic` valuta via LLM se contesto/risposta bozza sono sufficienti. Se non lo sono (e il budget `AGENT_MAX_ITERATIONS` non è esaurito), riformula `user_query` e instrada di nuovo verso lo **stesso** tool del giro precedente (`route_after_critic`) per un nuovo round di retrieval, invece di terminare. L'intent `direct` salta il critic. Il retry **sovrascrive** (non accumula) il contesto del giro precedente.
* **Verifica live:** su una domanda fuori tema (non presente nel documento) il loop ha eseguito 3 iterazioni reali con query progressivamente riformulata, esaurendo il budget e rispondendo onestamente "non ho informazioni" invece di inventare.

### 4.4. Parsing PDF layout-aware (CPU-only)
* **Stato:** Completato in `services/parsing.py` — `pypdf` sostituito da `pdfplumber`.
* **Implementazione:** Rilevamento tabelle con `table_settings={"vertical_strategy": "lines_strict", "horizontal_strategy": "lines_strict"}` (le strategie di default producevano falsi positivi sistematici su prosa densa senza vera griglia tabellare, verificato su un dossier parlamentare reale). Le tabelle vengono escluse dal testo libero ed estratte separatamente come Markdown; le pagine con immagini vengono segnalate senza modello vision.

### 4.5. Fix soglia pre-rerank (bug trovato in verifica live)
* **Stato:** Completato in `services/rag_engine.py` e `services/agent/tools/vector_tool.py`.
* **Problema:** `retrieval_score_threshold` veniva applicato al punteggio di fusione RRF (Qdrant) **prima** del re-ranking col cross-encoder. Il punteggio RRF è solo una misura di posizione tra le liste dense/sparse, non di rilevanza semantica — filtrare su di esso scartava candidati validi prima che il reranker potesse valutarli. Verificato in produzione: il chunk con la definizione esatta richiesta da una query (score RRF 0.08) veniva scartato sotto soglia 0.25, causando una risposta "non ho informazioni" nonostante un contesto di 16k caratteri parzialmente pertinente.
* **Fix:** il cross-encoder ora valuta l'intero pool oversampled (`search_k = top_k * retrieval_oversampling_factor`); la soglia resta solo come pavimento minimo nel fallback lessicale (quando il cross-encoder non è disponibile).

### 4.6. Altri fix minori
* Rimosso un leak di terminologia interna ("community") dalle risposte sintetizzate di `community_tool` (ora "argomenti trattati nel documento").
* Aggiunto supporto Alembic nell'immagine Docker del backend — `alembic.ini`/`alembic/` non erano mai stati copiati nell'immagine, quindi le migrazioni non erano mai state eseguibili in produzione prima d'ora.

### File coinvolti Fase 4
* `backend/app/services/sparse_vectors.py`, `backend/app/services/sparse_corpus_stats.py` — BM25 globale.
* `backend/alembic/versions/20260619_0008_sparse_bm25_global_stats.py` — migrazione.
* `backend/app/models/models.py` — `SparseTerm`, `Document.sparse_term_counts`/`sparse_total_tokens`.
* `backend/app/services/community_detection.py` — gerarchia leaf/root.
* `backend/app/services/agent/tools/community_tool.py` — preferenza riassunti root, fix wording.
* `backend/app/services/agent/state.py`, `backend/app/services/agent/nodes.py`, `backend/app/services/agent/graph.py` — loop critic.
* `backend/app/services/parsing.py` — parsing layout-aware con `pdfplumber`.
* `backend/app/services/rag_engine.py`, `backend/app/services/agent/tools/vector_tool.py` — fix soglia pre-rerank.
* `backend/Dockerfile`, `docker-compose.yml` — supporto Alembic nel container.
* `backend/tests/test_sparse_vectors.py`, `test_sparse_corpus_stats.py`, `test_community_detection.py`, `test_community_tool.py`, `test_agent_nodes.py`, `test_agent_graph.py`.

---

## Fase 5: Modelli GPT-5.4 differenziati per funzione e fix critic ✅ COMPLETATA

### 5.1. Modelli LLM a 3 livelli, scorporati da un'unica impostazione condivisa
* **Stato:** Completato in `backend/app/core/config.py`.
* **Problema risolto:** un solo `openai_model` (gpt-4o-mini) guidava router, synthesizer, critic e generazione Cypher.
* **Implementazione:** 3 livelli in base a volume di chiamate e bisogno di ragionamento:
    * `openai_model` (sintesi finale + critic, 1-3 chiamate/domanda) → **gpt-5.4**.
    * `router_model` / `cypher_model` (nuove impostazioni; classificazione/generazione strutturata, 1 chiamata/domanda) → **gpt-5.4-mini**.
    * `contextual_retrieval_model` / `community_summary_model` (alto volume in ingestion/community detection) → **gpt-5.4-nano**.
* **Attenzione in deploy:** il file `.env` del progetto aveva `OPENAI_MODEL` impostato esplicitamente, che sovrascrive sia il default Python sia quello in `docker-compose.yml` — controllare sempre tutti e tre i livelli quando un nuovo default non sembra avere effetto.

### 5.2. Fix bug troncamento input del critic
* **Stato:** Completato in `backend/app/services/agent/nodes.py::critic_node`.
* **Problema:** il critic giudicava `context[:6000]`/`answer[:2000]` — limiti invisibili con gpt-4o-mini (risposte terse) ma che con gpt-5.4 (più verboso) e contesti più ricchi (16k+ caratteri dopo la Fase 4) tagliavano la bozza a metà frase, causando falsi verdetti "insufficiente" (risposta tronca / fonti non nel contesto) su ogni domanda — 3 iterazioni sempre esaurite invece di 1.
* **Fix:** limiti alzati a 40000/12000 caratteri (argine solo per input patologici). Verificato dal vivo su query factual, relational e summary: tutte convergono ora in 1 iterazione genuina.

### File coinvolti Fase 5
* `backend/app/core/config.py` — `router_model`, `cypher_model`, nuovi default gpt-5.4/-mini/-nano.
* `backend/app/services/agent/router.py`, `backend/app/services/agent/tools/cypher_tool.py` — uso dei nuovi model setting.
* `backend/app/services/agent/nodes.py` — fix troncamento critic.
* `docker-compose.yml`, `librechat/librechat.yaml` — mirror env var, etichetta modello cosmetica.

---
