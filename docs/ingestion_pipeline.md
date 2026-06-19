# Ingestion Pipeline

## Current Flow

1. Upload validates type and size, stores the original file in MinIO, and creates a `Document` in `uploaded`.
2. Celery starts `process_document()` with task metadata.
3. The pipeline creates or resumes an `IngestionJob`, cleans derived artifacts, then moves through `parsing`, `chunking`, `embedding`, `vector_indexing`, and `graph_indexing`.
4. Chunk IDs and Qdrant point IDs are deterministic, so retries rebuild instead of duplicating.
5. Qdrant payloads include `user_id`, `document_id`, `text_hash`, `token_count`, `section_title`, `char_start`, `char_end`, `page_start`, `page_end`, `document_page_count`, and status metadata.
6. Sparse vectors use a real, global BM25 (`services/sparse_vectors.py` + `services/sparse_corpus_stats.py`): a stable term vocabulary in Postgres (`sparse_terms`), with IDF/avg-doc-length computed over the *entire* indexed corpus (not just the current document) and cached in Redis (`bm25:vocab`/`bm25:df`/`bm25:total_chunks`/`bm25:total_tokens`). Each `Document` stores its own term-count contribution (`sparse_term_counts`/`sparse_total_tokens`) so it can be cleanly subtracted from the global stats on delete/reindex.
7. Neo4j receives document, chunk, entity, and relation data after vector indexing succeeds:
   - **Entities** are extracted from **every chunk** using the local **GLiNER** NER model.
   - **Relations** are inferred by the LLM, also over **every chunk** — no chunk cap (a previous chunk cap left most entities in long documents without any entity-entity relation).

## Recovery Rules

- `completed` documents are skipped unless explicitly reindexed.
- Failed documents can be uploaded again or reindexed; retries clean Postgres chunks, Qdrant points, and Neo4j nodes for that document.
- `IngestionJob` records keep phase, progress, retry count, error code, and timestamps for diagnostics.

## Configuration

Key environment variables for the graph extraction stage:

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_GLINER` | `true` | Enable local GLiNER entity extraction |
| `GLINER_MODEL` | `gliner-community/gliner_small-v2.5` | Hugging Face model used for NER |
| `GLINER_LABELS` | `Persona,Organizzazione,...` | Comma-separated entity labels |
| `GLINER_THRESHOLD` | `0.5` | Confidence threshold for accepted entities |

## Next Quality Gates

- Store golden retrieval cases using the shape in `docs/retrieval_eval_example.json`.
- Run `cd backend && python scripts/evaluate_retrieval.py ../docs/retrieval_eval_example.json --k 5`.
- Run precision@k, recall@k, and document coverage before changing chunking or embedding defaults.
- Enable OCR with `ENABLE_OCR=true` only after installing optional OCR runtime dependencies (`pypdfium2`, `pytesseract`, and the system `tesseract` binary).
- By default, retrieval uses Qdrant dense+sparse fusion plus local lexical reranking.
- Existing dense-only Qdrant collections must be reset or recreated before reindexing with `QDRANT_ENABLE_NATIVE_SPARSE=true`.
- Run Qdrant integration smoke tests with `RUN_INTEGRATION_TESTS=1 pytest tests/test_qdrant_integration.py` while Qdrant is reachable at `QDRANT_URL` or `http://localhost:6333`.

## End-to-End Smoke Test

Start dependency-only services:

```bash
docker compose -f docker-compose.integration.yml up -d
cd backend
python scripts/e2e_ingestion_smoke.py
```

Or through pytest:

```bash
cd backend
RUN_E2E_TESTS=1 pytest tests/test_ingestion_e2e.py
```

Stop services with:

```bash
docker compose -f docker-compose.integration.yml down -v
```
