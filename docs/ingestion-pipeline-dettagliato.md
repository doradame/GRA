# Pipeline di Ingestion — Analisi dettagliata dal codice

> Documento generato a partire dal codice sorgente di `graph-rag-assistant/backend/app/`.
> File principali coinvolti: `routers/documents.py`, `tasks/ingestion.py`, `services/ingestion.py`, `services/parsing.py`, `services/chunking.py`, `services/embeddings.py`, `services/sparse_vectors.py`, `services/vector_store.py`, `services/graph_store.py`, `services/extraction.py`, `services/storage.py`, `models/models.py`, `core/config.py`, `core/celery_app.py`.

---

## 1. Panoramica

L’ingestion è il processo che trasforma un file caricato dall’utente in una rappresentazione interrogabile all’interno della knowledge base. Il sistema adotta un’architettura **asincrona basata su Celery**:

1. L’utente carica un file tramite l’endpoint `/api/v1/documents/upload`.
2. Il backend valida il file, lo salva su MinIO e crea un record nel database PostgreSQL.
3. Se il documento è schedulabile, viene invocato il task Celery `ingest_document_task`.
4. Il worker Celery esegue `process_document` in un nuovo event loop, passando attraverso le fasi di parsing, chunking, embedding, indicizzazione vettoriale (Qdrant) e costruzione del grafo (Neo4j).

Le fasi sono tracciate nel campo `Document.status` e dettagliate nella tabella `IngestionJob`.

---

## 2. Endpoint di upload — `routers/documents.py`

### 2.1 Validazione del file

L’endpoint `POST /api/v1/documents/upload` accetta un `UploadFile` e applica i seguenti controlli:

- **`content_type` obbligatorio**: se mancante, ritorna `400 Bad Request`.
- **Content type supportato**: deve appartenere a un elenco esplicito oppure iniziare con `text/`:
  - `application/pdf`
  - `application/vnd.openxmlformats-officedocument.wordprocessingml.document`
  - `application/msword`
  - `text/plain`
  - `text/markdown`
  - `text/csv`
  - `text/html`
  - `application/json`
- **File non vuoto**: `400` se `len(data) == 0`.
- **Limite dimensione**: `MAX_UPLOAD_BYTES = 100 MiB`; superato il limite ritorna `413 Payload Too Large`.

### 2.2 Creazione del record e deduplicazione

Dopo la validazione viene chiamata `create_document` in `services/ingestion.py`. Se esiste già un documento con lo stesso `content_hash` per lo stesso utente (`created_by`), il record esistente viene restituito senza creare duplicati. La deduplicazione è **per-utente**: non viene condivisa tra utenti diversi per evitare leak di metadati.

### 2.3 Scheduling del task

Se il documento si trova in uno stato schedulabile (`uploaded` o `error`), viene invocato:

```python
ingest_document_task.delay(
    document_id=str(doc.id),
    filename=doc.filename,
    content_type=doc.content_type,
    storage_key=doc.storage_key,
    user_id=str(current_user.id),
)
```

Se il documento era già `completed`, viene restituito così com’è.

### 2.4 Reindex e cancellazione

- `POST /api/v1/documents/{id}/reindex`: imposta `status = "uploaded"`, cancella `error_message` e rilancia il task Celery.
- `DELETE /api/v1/documents/{id}`: elimina i dati da Neo4j (`graph_store.delete_document`), da Qdrant (`vector_store.delete_by_document`), da MinIO (`storage.delete`) e infine il record dal database.
- `POST /api/v1/documents/reset` (solo admin): resetta l’intero grafo, l’intera collezione Qdrant, i contatori API usage e tutti i documenti.

---

## 3. Task Celery — `tasks/ingestion.py`

Il task `ingest_document_task` è definito come `@shared_task(bind=True, max_retries=3)`.

- Riceve i parametri `document_id`, `filename`, `content_type`, `storage_key`, `user_id`.
- Esegue `asyncio.run(process_document(...))` passando anche `task_id=self.request.id` e `retry_count=self.request.retries`.
- In caso di errore logga l’eccezione e rilancia il task con `self.retry(exc=exc, countdown=60)`, fino a 3 tentativi.
- Il worker è configurato in `core/celery_app.py` con:
  - `task_time_limit=3600` (hard limit 1 ora)
  - `task_soft_time_limit=3300` (soft limit 55 minuti)
  - `worker_prefetch_multiplier=1`
  - `task_track_started=True`, `worker_send_task_events=True`, `task_send_sent_event=True`

---

## 4. Pipeline di ingestion — `services/ingestion.py`

`process_document` è il cuore della pipeline. Crea un proprio engine/sessione SQLAlchemy async (`create_async_engine` + `async_sessionmaker`) per poter girare in modo isolato all’interno del worker Celery.

### 4.1 Stati e progressi

Gli stati definiti sono:

```python
STATUS_UPLOADED        = "uploaded"        # progresso 0
STATUS_PARSING         = "parsing"         # progresso 10
STATUS_CHUNKING        = "chunking"        # progresso 25
STATUS_EMBEDDING       = "embedding"       # progresso 45
STATUS_VECTOR_INDEXING = "vector_indexing" # progresso 65
STATUS_GRAPH_INDEXING  = "graph_indexing"  # progresso 80
STATUS_COMPLETED       = "completed"       # progresso 100
STATUS_ERROR           = "error"           # progresso 100
```

La funzione `_set_document_status` aggiorna sia `Document.status` che i campi dell’`IngestionJob` corrispondente (`phase`, `progress`, `status`, `error_code`, `error_message`, `completed_at`, `started_at`).

### 4.2 Job tracking

`_get_or_create_job` cerca un job esistente per quel `document_id` (opzionalmente filtrato per `task_id`) e ne aggiorna `retry_count`, `status`, `error_*`. Se non esiste, ne crea uno nuovo in stato `running` con `phase=uploaded` e `progress=0`.

### 4.3 Pulizia artefatti precedenti

All’inizio della pipeline (`_cleanup_document_artifacts`) vengono eliminati eventuali dati derivati precedenti:

- cancellazione dei record `Chunk` dal database
- cancellazione dei punti Qdrant associati al documento
- cancellazione dei nodi/relazioni Neo4j associate al documento

Questo rende i retry **deterministici**: ogni esecuzione riparte da zero.

### 4.4 Flusso dettagliato

#### Fase 1: Parsing (`STATUS_PARSING`, progresso 10)

1. Scarica il file originale da MinIO con `storage.download(storage_key)`.
2. Chiama `extract_document(filename, data, enable_ocr, min_text_chars_for_ocr)`.
3. Memorizza nel record `Document`:
   - `parser`
   - `page_count`
   - `text_chars = len(text)`
   - `ocr_used`
4. Se il testo estratto è vuoto, solleva `ValueError("No extractable text found in document")`.

#### Fase 2: Chunking (`STATUS_CHUNKING`, progresso 25)

1. Chiama `chunk_text(text)`.
2. Se non viene prodotto alcun chunk, solleva `ValueError("Document text did not produce any chunks")`.

#### Fase 3: Embedding (`STATUS_EMBEDDING`, progresso 45)

1. Chiama `embed_texts(chunks)` in modo asincrono.
2. Verifica che `len(embeddings) == len(chunks)`, altrimenti errore.

#### Fase 4: Costruzione record Chunk e punti Qdrant

Per ogni coppia `(chunk_text, embedding)` viene calcolato:

- `text_hash = SHA256(chunk_text)`
- `token_count` tramite `tiktoken` (o stima fallback basata sulle parole)
- `section_title` estrapolato dalla prima riga del chunk (se ≤ 120 caratteri e tutta maiuscola o non terminante per `. : ; ,`)
- `span_start`, `span_end` tramite `_find_chunk_span`, che cerca la posizione del chunk nel testo completo
- `page_start`, `page_end` calcolati a partire dalle informazioni di pagina restituite dal parser
- `chunk_id = stable_uuid("chunk", document_id, idx, text_hash)`
- `qdrant_id = chunk_id`

Vengono quindi creati:

- un oggetto `Chunk` da salvare in PostgreSQL
- un `PointStruct` Qdrant con payload ricco (testo, metadati, pagine, hash, titolo sezione, stato, ecc.)

I vettori Qdrant sono costruiti con `vector_store.build_point_vector(embedding, build_sparse_vector(chunk_text))`, quindi includono sia il vettore denso che quello sparso (se abilitato).

#### Fase 5: Indicizzazione vettoriale (`STATUS_VECTOR_INDEXING`, progresso 65)

1. Inserisce in blocco i record `Chunk` nel database con `db.add_all(chunk_records)`.
2. Effettua l’upsert in Qdrant con `vector_store.upsert(qdrant_points)`, eventualmente in batch secondo `settings.qdrant_upsert_batch_size` (default 500).

#### Fase 6: Indicizzazione grafo (`STATUS_GRAPH_INDEXING`, progresso 80)

1. Crea il nodo `Document` in Neo4j con `graph_store.add_document(...)`.
2. Per ogni chunk:
   - crea il nodo `Chunk` e la relazione `BELONGS_TO` verso il documento (`graph_store.add_chunk`)
   - se `idx < max_graph_extraction_chunks` (default 48), estrae entità e relazioni tramite `extract_entities_relations(chunk_text)`
   - le entità/relazioni estratte vengono aggiunte al grafo con `graph_store.add_entities_and_relations`
   - se `idx >= max_graph_extraction_chunks`, l’estrazione viene saltata per i chunk successivi
3. Il progresso della fase grafo viene aggiornato progressivamente con formula `80 + ((idx+1) / n_chunks) * 18`.

#### Fase 7: Completamento

Se tutto va a buon fine, `_set_document_status(db, doc, STATUS_COMPLETED, job=job)` marca il documento e il job come completati.

### 4.5 Gestione errori

Se una qualsiasi fase solleva un’eccezione:

1. Viene eseguito `db.rollback()`.
2. Viene chiamata `_cleanup_document_artifacts` per eliminare i dati parziali.
3. Il documento e il job vengono marcati come `error` con `error_code = type(e).__name__` e `error_message = str(e)[:4000]`.
4. L’eccezione viene rilanciata in modo che Celery possa riprovare (fino a 3 volte).

---

## 5. Parsing — `services/parsing.py`

Il parsing determina il formato in base al MIME type rilevato con `python-magic` e, in fallback, all’estensione del file.

### 5.1 PDF

- Usa `pypdf.PdfReader`.
- Per ogni pagina chiama `page.extract_text()`.
- Costruisce una lista di `PageText(page, text, start_char, end_char)` che mantiene la mappa carattere→pagina.
- Il testo completo è l’unione delle pagine separate da `\n\n`.
- Se `enable_ocr=True` e il testo estratto è più corto di `min_text_chars_for_ocr`, tenta l’OCR con `pypdfium2` + `pytesseract`, renderizzando ogni pagina a scale=2.

### 5.2 DOCX/DOC

- Usa `python-docx.Document`.
- Estrae il testo di ogni paragrafo non vuoto, uniti da `\n\n`.

### 5.3 Testo semplice

- Decodifica i byte come UTF-8 ignorando gli errori.

### 5.4 HTML

- Usa `BeautifulSoup` in modalità `html.parser`.
- Rimuove tag `<script>` e `<style>`.
- Restituisce il testo con `\n` come separatore.

### 5.5 Fallback

- Se il MIME type non è riconosciuto, tenta la decodifica UTF-8 con parser `text_fallback`.

---

## 6. Chunking — `services/chunking.py`

La funzione `chunk_text` suddivide il testo in chunk semanticamente coerenti.

Parametri default:

- `max_tokens = 512`
- `overlap_tokens = 64`
- `model = "text-embedding-3-large"`

Logica:

1. Divide il testo in paragrafi (`\n\n`).
2. Per ogni paragrafo calcola la tokenizzazione con `tiktoken` (fallback a split per parole se il modello non è riconosciuto).
3. Se un paragrafo supera `max_tokens`, viene ulteriormente diviso per frasi (spezzando su `. `).
4. Accumula paragrafi/frasi in un buffer finché non si supera `max_tokens`; a quel punto emette un chunk.
5. Quando si chiude un chunk, applica un overlap di `overlap_tokens` usando `_apply_overlap`, che prende le ultime parti del chunk precedente (tokenizzate con encoding `gpt-4` come riferimento).
6. L’ultimo buffer residuo viene emesso come chunk finale.

**Osservazione**: `_apply_overlap` calcola l’overlap sul numero di token, ma l’overlap effettivo potrebbe non essere esattamente `overlap_tokens` se una singola parte (paragrafo/frase) lo supera.

---

## 7. Embeddings — `services/embeddings.py`

`embed_texts` genera i vettori densi per i chunk.

### 7.1 Modalità demo

Se `OPENAI_API_KEY` è assente o inizia con `sk-test`, viene usata `_fallback_embedding`:

- seed = SHA256 del testo
- vettore deterministico di dimensione `settings.embedding_dimensions` (default 3072)
- normalizzazione L2

Questa modalità permette di testare lo stack senza chiave OpenAI, ma le risposte non sono semanticamente significative.

### 7.2 Modalità OpenAI

- Crea un client `AsyncOpenAI` fresco per l’event loop corrente.
- Processa i chunk in batch di dimensione `settings.embedding_batch_size` (default 96).
- Chiama `client.embeddings.create` con `model=settings.embedding_model` (default `text-embedding-3-large`).
- Se specificato, passa `dimensions=settings.embedding_dimensions`.
- Se il modello/API rifiuta il parametro `dimensions` (`BadRequestError`), ritenta senza.
- Traccia i token usati tramite `increment_embeddings_calls`.

---

## 8. Vettori sparsi — `services/sparse_vectors.py`

I vettori sparsi sono opzionali e controllati da `settings.qdrant_enable_native_sparse` (default `False`).

`build_sparse_vector`:

1. Tokenizza il testo con regex `r"[\wÀ-ÿ]{3,}"` in lowercase.
2. Rimuove stopwords inglesi e italiane (elenco hardcoded di 21 termini).
3. Per ogni token calcola un indice con `BLAKE2b` digest di 8 byte modulo 1.000.003 bucket.
4. Somma i pesi `1 + log(count)` per token che collidono nello stesso bucket.
5. Normalizza L2.
6. Restituisce un `SparseVector` ordinato per indice.

Questo fornisce una rappresentazione bag-of-words pesata per la ricerca ibrida su Qdrant.

---

## 9. Vector Store — `services/vector_store.py`

Wrapper attorno a `QdrantClient`.

### 9.1 Inizializzazione

- Connessione a `settings.qdrant_url`.
- Se la collezione non esiste, la crea:
  - vettore denso con distanza COSINE e dimensione `settings.embedding_dimensions`
  - vettore sparso (se `qdrant_enable_native_sparse=True`)
- Se la collezione esiste e lo sparse è abilitato, verifica che il vettore sparso sia presente; altrimenti logga un warning.

### 9.2 Upsert

`upsert(points, batch_size)` invia i punti a Qdrant in batch. Il default batch size è 500.

### 9.3 Ricerca

- `search`: ricerca per similarità coseno sul vettore denso.
- `search_hybrid`: se lo sparse è abilitato, esegue due prefetch (denso e sparso) e fonde i risultati con Reciprocal Rank Fusion (`Fusion.RRF`); in fallback torna alla ricerca densa.
- `build_point_vector`: costruisce il payload vettoriale compatibile con la configurazione.
- `delete_by_document`: elimina tutti i punti con `document_id` corrispondente.
- `reset_collection`: cancella e ricrea la collezione.

---

## 10. Graph Store — `services/graph_store.py`

Wrapper attorno al driver Neo4j.

### 10.1 Inizializzazione

- Connessione a `settings.neo4j_uri` con `settings.neo4j_user` / `settings.neo4j_password`.
- Attende che Neo4j sia disponibile con retry (max 30 tentativi, 1 secondo di attesa).
- Crea vincoli di unicità su `Entity.id`, `Chunk.id`, `Document.id`.

### 10.2 Schema del grafo

Nodi:

- `:Document {id, filename, content_type, user_id}`
- `:Chunk {id, text, index, user_id}`
- `:Entity {id, name, type, normalized_name}`

Relazioni:

- `(Chunk)-[:BELONGS_TO]->(Document)`
- `(Chunk)-[:MENTIONS]->(Entity)`
- `(Entity)-[:<TIPO_REL>]->(Entity)` (tipi dinamici sanitizzati)

### 10.3 Operazioni principali

- `add_document`: `MERGE` del nodo Document con proprietà aggiornate.
- `add_chunk`: `MERGE` del nodo Chunk, relazione `BELONGS_TO` verso il Document.
- `add_entities_and_relations`: per ogni entità fa `MERGE` con relazione `MENTIONS` dal chunk; per ogni relazione fa `MERGE` tra entità con tipo relazione sanitizzato.
- `delete_document`: elimina il documento, i suoi chunk e le relazioni dei chunk; poi elimina le entità che non sono più menzionate da alcun chunk.
- `reset`: `MATCH (n) DETACH DELETE n`.
- `explore_entity` / `get_stats`: utility per esplorazione e metriche.

---

## 11. Estrazione entità e relazioni — `services/extraction.py`

Per ogni chunk (fino al limite `max_graph_extraction_chunks`) viene chiamato un LLM OpenAI per estrarre entità e relazioni.

### 11.1 Schema JSON

```json
{
  "entities": [{ "id": "...", "name": "...", "type": "..." }],
  "relations": [{ "source_id": "...", "target_id": "...", "type": "...", "properties": {} }]
}
```

### 11.2 Prompt

Il prompt (in italiano) richiede di estrarre entità rilevanti (persone, organizzazioni, prodotti, concetti, regole, requisiti, rischi, date, numeri) e relazioni significative (richiede, esclude, include, si riferisce a, limita, dipende da, è parte di).

### 11.3 Modalità di chiamata

- Se `OPENAI_API_KEY` è assente o `sk-test`, ritorna entità/relazioni vuote.
- Il testo inviato al LLM è troncato a 8000 caratteri (`text[:8000]`).
- Prima tenta `response_format={"type": "json_schema", ...}` (con `strict=True`).
- Se il modello/API non supporta JSON schema (`BadRequestError`), passa a `response_format={"type": "json_object"}` con un system prompt che descrive la forma attesa.
- Traccia i token usati tramite `increment_extraction_calls`.

### 11.4 Normalizzazione

`_normalize_extraction`:

- converte eventuali dizionari di entità in liste
- normalizza entità stringa in `{name, type: "Unknown"}`
- calcola un `canonical_id` stabile come SHA256 di `"tipo:nome"` (lowercase, spazi normalizzati)
- deduplica entità per `canonical_id`
- mappa gli `id` temporanei del LLM ai `canonical_id`
- filtra relazioni con `source_id` o `target_id` non validi o uguali
- deduplica relazioni per `(source_id, target_id, type.lower())`
- gestisce `properties` come dizionario opzionale

---

## 12. Storage — `services/storage.py`

Wrapper attorno a MinIO (API S3 compatibile).

- `upload(key, data, content_type)`: salva l’oggetto nel bucket `settings.minio_bucket`.
- `download(key)`: recupera l’oggetto e ne restituisce i byte.
- `delete(key)`: rimuove l’oggetto.
- Alla prima connessione verifica/creating il bucket.
- Connessione non sicura (`secure=False`) all’endpoint `settings.minio_endpoint`.

---

## 13. Modelli database — `models/models.py`

### 13.1 `User`

- `id` (UUID PK)
- `email`, `hashed_password`, `is_active`, `is_admin`, `created_at`

### 13.2 `Document`

- `id` (UUID PK)
- `filename` (max 512)
- `content_hash` (SHA256, indexed, usato per deduplicazione)
- `content_type`, `size_bytes`
- `storage_key` (percorso MinIO: `{user_id}/{doc_id}/{filename}`)
- `parser`, `page_count`, `text_chars`, `ocr_used`
- `status` (stringa descrittiva)
- `error_message`
- `created_by` (FK → User)
- `created_at`, `updated_at`
- Vincolo di unicità `(created_by, content_hash)`

### 13.3 `Chunk`

- `id` (UUID PK)
- `document_id` (FK → Document ON DELETE CASCADE)
- `chunk_index` (posizione nel documento)
- `text`, `text_hash` (SHA256)
- `token_count`
- `section_title`
- `char_start`, `char_end` (posizione nel testo originale)
- `page_start`, `page_end`
- `qdrant_point_id` (stringa, corrisponde all’ID punto Qdrant)
- Vincolo di unicità `(document_id, chunk_index)`

### 13.4 `IngestionJob`

- `id` (UUID PK)
- `document_id` (FK, indexed)
- `task_id` (Celery task ID, indexed)
- `status` (queued/running/completed/error)
- `phase` (stato corrente della pipeline)
- `progress` (intero 0-100)
- `retry_count`
- `error_code`, `error_message`
- `started_at`, `completed_at`, `created_at`, `updated_at`

---

## 14. Configurazione rilevante — `core/config.py`

Parametri che influenzano direttamente l’ingestion:

| Parametro | Default | Effetto |
|-----------|---------|---------|
| `embedding_model` | `text-embedding-3-large` | Modello embedding OpenAI |
| `embedding_dimensions` | `3072` | Dimensione vettori densi |
| `embedding_batch_size` | `96` | Batch per chiamate embedding |
| `enable_ocr` | `False` | Abilita OCR fallback per PDF |
| `min_text_chars_for_ocr` | `100` | Soglia testo minimo per scatenare OCR |
| `max_graph_extraction_chunks` | `48` | Numero massimo di chunk da sottoporre a estrazione entità/relazioni |
| `qdrant_collection` | `insurance_chunks` | Nome collezione Qdrant |
| `qdrant_enable_native_sparse` | `False` | Abilita vettori sparsi nativi |
| `qdrant_upsert_batch_size` | `500` | Batch upsert Qdrant |
| `openai_api_key` | `""` | Chiave API; `sk-test` attiva modalità demo |
| `openai_model` | `gpt-4o-mini` | Modello per estrazione entità/relazioni |

---

## 15. Flusso end-to-end

```
Utente
  │ POST /api/v1/documents/upload
  ▼
routers/documents.py
  ├── validazione file
  ├── create_document()
  │   ├── calcolo content_hash
  │   ├── deduplicazione per utente
  │   ├── upload su MinIO
  │   └── INSERT Document (status=uploaded)
  └── ingest_document_task.delay(...)
              │
              ▼
      tasks/ingestion.py
              │
              ▼
      asyncio.run(process_document(...))
              │
              ▼
      services/ingestion.py
              │
              ├── cleanup artefatti precedenti
              ├── STATUS_PARSING
              │   └── extract_document() → testo + pagine
              ├── STATUS_CHUNKING
              │   └── chunk_text() → lista chunk
              ├── STATUS_EMBEDDING
              │   └── embed_texts() → lista vettori
              ├── creazione oggetti Chunk + PointStruct
              ├── STATUS_VECTOR_INDEXING
              │   ├── INSERT Chunk in PostgreSQL
              │   └── upsert in Qdrant
              ├── STATUS_GRAPH_INDEXING
              │   ├── add_document in Neo4j
              │   ├── per ogni chunk:
              │   │   ├── add_chunk
              │   │   └── se idx < max_graph_extraction_chunks:
              │   │       ├── extract_entities_relations()
              │   │       └── add_entities_and_relations()
              │   └── aggiornamento progresso
              └── STATUS_COMPLETED
```

---

## 16. Osservazioni e possibili miglioramenti

1. **Estrazione grafo limitata ai primi 48 chunk**: documenti lunghi perdono le entità/relazioni dei chunk successivi. Si potrebbe rendere configurabile o campionare chunk rappresentativi.

2. **OCR disabilitato di default**: i PDF scannerizzati non vengono processati se non si imposta `ENABLE_OCR=true`. Inoltre l’OCR perde le informazioni di pagina (`pages`) perché `_extract_pdf_ocr` non restituisce `PageText`.

3. **Fallback embedding deterministico**: in modalità demo i vettori non sono semantici; la ricerca vettoriale restituirà risultati apparentemente casuali.

4. **Stopwords sparse hardcoded**: solo 21 termini. Per lingue diverse o domini specifici andrebbe usata una lista più ampia.

5. **Chunking per frasi**: la suddivisione su `. ` può fallire con abbreviazioni o numeri decimali. Si potrebbe usare un sentence splitter più robusto (es. `nltk` o `spacy`).

6. **Transazioni distribuite**: non c’è un meccanismo di atomicità tra PostgreSQL, Qdrant e Neo4j. Un fallimento dopo l’upsert Qdrant ma prima del commit Neo4j lascia gli store in uno stato inconsistente fino al retry.

7. **Retry**: il cleanup all’inizio del task aiuta, ma se il worker crasha durante l’upsert di un batch grande potrebbero rimanere punti orfani in Qdrant.

8. **Progresso**: la fase di embedding e vector indexing non aggiornano il progresso internamente; per documenti con migliaia di chunk l’admin UI vedrebbe lunghi stalli al 45% e 65%.

9. **Sicurezza della deduplicazione**: correttamente scoped per utente, ma un utente che carica lo stesso file più volte ottiene sempre lo stesso `Document` esistente, anche se il precedente era in `error` (viene solo resettato a `uploaded` e rischedulato).

10. **Filename**: viene sanitizzato (`_safe_filename`) sostituendo caratteri non alfanumerici con `_` e troncato a 180 caratteri.

---

## 17. File e funzioni di riferimento

| File | Funzione / Classe principale | Ruolo |
|------|------------------------------|-------|
| `routers/documents.py` | `upload_document`, `reindex_document`, `delete_document` | API REST |
| `tasks/ingestion.py` | `ingest_document_task` | Wrapper Celery |
| `services/ingestion.py` | `create_document`, `process_document` | Pipeline orchestration |
| `services/parsing.py` | `extract_document`, `_extract_pdf`, `_extract_docx`, `_extract_html` | Estrazione testo |
| `services/chunking.py` | `chunk_text` | Segmentazione |
| `services/embeddings.py` | `embed_texts`, `_fallback_embedding` | Embedding denso |
| `services/sparse_vectors.py` | `build_sparse_vector` | Embedding sparso |
| `services/vector_store.py` | `VectorStore.upsert`, `search_hybrid` | Qdrant |
| `services/graph_store.py` | `GraphStore.add_*`, `delete_document` | Neo4j |
| `services/extraction.py` | `extract_entities_relations` | LLM entity/relation extraction |
| `services/storage.py` | `DocumentStorage.upload/download/delete` | MinIO |
| `models/models.py` | `Document`, `Chunk`, `IngestionJob` | Schema DB |
| `core/config.py` | `Settings` | Configurazione |
| `core/celery_app.py` | `celery_app` | Broker/task config |
