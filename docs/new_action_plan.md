# Action Plan: Evoluzione Architettura GraphRAG Ibrida

**Obiettivo:** Trasformare l'attuale pipeline di ingestion e retrieval da un sistema RAG documentale di base a un ecosistema GraphRAG agentico e scalabile, superando i limiti di estrazione parziale e migliorando la precisione del retrieval tramite vettori sparsi avanzati e navigazione topologica del grafo.

**Stato attuale (aggiornato al 18/06/2026):**
* ✅ Fase 1 completata — vettori sparsi BM25 + entity resolution fuzzy con APOC.
* ✅ Fase 2 completata — estrazione entità con GLiNER su tutti i chunk, relazioni solo via LLM.
* 🔄 Fase 3 in corso / da pianificare — orchestrazione agentica con LangGraph, Local/Global Graph Search.

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

## Fase 3: Orchestrazione Agentica e Retrieval Avanzato

Sostituire la singola catena di query statica con un workflow decisionale in grado di instradare la domanda verso lo strumento più adatto.

### 3.1. Integrazione Framework Agentico (LangGraph)
* **Azione:** Riscrivere il modulo di query/retrieval utilizzando **LangGraph** (o equivalente state-machine framework).
* **Componenti:**
    * **Semantic Router (Nodo di Inizio):** Analizza l'intento della query.
    * **Vector Tool:** Instradamento per recupero fattuale classico via Qdrant.
    * **Text2Cypher Tool:** Instradamento per domande relazionali complesse (es. "Quali sistemi sono bloccati dal firewall X?"). L'agente genera Cypher e lo esegue direttamente su Neo4j.

### 3.2. Local Graph Search (Iniezione di Contesto Topologico)
* **Azione:** Arricchire il Vector Tool standard.
* **Implementazione:** Quando Qdrant restituisce i top-K chunk, intercettare i `chunk_ids`. Eseguire una query rapida su Neo4j per estrarre il sottografo locale:
    ```cypher
    MATCH (c:Chunk)-[:MENTIONS]->(e:Entity)-[r]-(e2:Entity) 
    WHERE c.id IN $chunk_ids 
    RETURN e, r, e2
    ```
* **Iniezione:** Serializzare queste relazioni in testo (es. *"L'entità X ha una relazione Y con Z"*) e iniettarle nel prompt del LLM assieme ai chunk grezzi.

### 3.3. Global Graph Summarization (Community Detection)
* **Azione:** Gestire le query di sintesi ad alto livello (es. "Quali sono le tematiche principali del documento?").
* **Implementazione:** Configurare un job Celery settimanale o giornaliero che utilizza la libreria *Graph Data Science (GDS)* di Neo4j.
    * Eseguire l'algoritmo di **Leiden** o **Louvain** per identificare cluster di entità.
    * Generare via LLM un riassunto per ogni cluster e salvarlo come nodo `:CommunitySummary`. L'agente interrogherà questi riassunti invece di eseguire letture massive o incappare in limiti di contesto.

---
