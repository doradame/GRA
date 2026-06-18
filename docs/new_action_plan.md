# Action Plan: Evoluzione Architettura GraphRAG Ibrida

**Obiettivo:** Trasformare l'attuale pipeline di ingestion e retrieval da un sistema RAG documentale di base a un ecosistema GraphRAG agentico e scalabile, superando i limiti di estrazione parziale e migliorando la precisione del retrieval tramite vettori sparsi avanzati e navigazione topologica del grafo.

---

## Fase 1: Ottimizzazione Fondamenta Dati (Vector & Graph Store)

Attualmente il sistema soffre di una gestione ingenua dei vettori sparsi e di una frammentazione delle entità nel grafo (deduplicazione solo per hash esatto).

### 1.1. Refactoring Vettori Sparsi (Sparse Embeddings)
L'attuale generazione in `services/sparse_vectors.py` basata su regex e 21 stopwords hardcoded non è adeguata per la lingua italiana e per domini complessi.
* **Azione:** Sostituire l'algoritmo attuale.
* **Implementazione:** Integrare la libreria `ranx` o un'implementazione BM25 robusta via `scikit-learn` / `NLTK` all'interno del worker Celery.
* **Requisito:** Mantenere la compatibilità in fase di upsert con il payload richiesto da Qdrant per la ricerca ibrida (RRF).

### 1.2. Entity Resolution Dinamica (Fuzzy Merging)
Risolvere la frammentazione dei nodi in Neo4j dovuta a minime variazioni nominali (es. "Banca d'Italia" vs "Banca d Italia").
* **Azione:** Creare un nuovo task Celery asincrono e schedulato (es. notturno).
* **Implementazione:** 1. Estrarre le entità da Neo4j e calcolare gli embedding dei nomi.
    2. Calcolare la similarità del coseno tra entità dello stesso tipo.
    3. Per valori di similarità `> 0.93`, eseguire il merging.
* **Cypher Reference:** Utilizzare la procedura APOC `CALL apoc.refactor.mergeNodes(nodes, {properties: 'combine', mergeRels: true})` per fondere i nodi preservando tutti gli archi `MENTIONS` esistenti.

---

## Fase 2: Sblocco Estrazione Grafo Completa

Il vincolo `max_graph_extraction_chunks` limitato ai primi 48 chunk per documento genera un grafo "monco". Dobbiamo separare l'estrazione delle entità (NER) da quella delle relazioni per ottimizzare tempi e costi.

### 2.1. Estrazione Entità via SLM Locale
* **Azione:** Modificare `services/extraction.py` per rimuovere il limite dei 48 chunk per il riconoscimento delle entità.
* **Implementazione:** Integrare **GLiNER** (Generalist and Lightweight Model for Named Entity Recognition). Far girare questo SLM localmente nel worker Celery per estrarre entità (Sistemi, Persone, Organizzazioni) da *tutti* i chunk del documento ad alta velocità.

### 2.2. Estrazione Relazioni Ottimizzata (LLM via Proxy)
* **Azione:** Limitare l'uso dei modelli generativi di classe GPT unicamente alla deduzione delle relazioni logiche.
* **Implementazione:** Passare al LLM il testo del chunk *insieme* alla lista pre-compilata delle entità trovate da GLiNER. Il prompt richiederà esclusivamente di mappare i collegamenti (es. "A dipende da B"). Continueremo a veicolare queste chiamate attraverso la nostra infrastruttura **LiteLLM** per standardizzare l'accesso ai modelli, tracciare i token e gestire eventuali fallback.

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
