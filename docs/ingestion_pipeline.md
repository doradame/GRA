# Ingestion Pipeline

## Current Flow

1. Upload validates type and size, stores the original file in MinIO, and creates a `Document` in `uploaded`.
2. Celery starts `process_document()` with task metadata.
3. The pipeline creates or resumes an `IngestionJob`, cleans derived artifacts, then moves through `parsing`, `chunking`, `embedding`, `vector_indexing`, and `graph_indexing`.
4. Chunk IDs and Qdrant point IDs are deterministic, so retries rebuild instead of duplicating.
5. Qdrant payloads include `user_id`, `document_id`, `text_hash`, `token_count`, `section_title`, and status metadata.
6. Neo4j receives document, chunk, entity, and relation data after vector indexing succeeds.

## Recovery Rules

- `completed` documents are skipped unless explicitly reindexed.
- Failed documents can be uploaded again or reindexed; retries clean Postgres chunks, Qdrant points, and Neo4j nodes for that document.
- `IngestionJob` records keep phase, progress, retry count, error code, and timestamps for diagnostics.

## Next Quality Gates

- Store golden retrieval cases using the shape in `docs/retrieval_eval_example.json`.
- Run `cd backend && python scripts/evaluate_retrieval.py ../docs/retrieval_eval_example.json --k 5`.
- Run precision@k, recall@k, and document coverage before changing chunking or embedding defaults.
- Enable OCR with `ENABLE_OCR=true` only after installing optional OCR runtime dependencies (`pypdfium2`, `pytesseract`, and the system `tesseract` binary).
- By default, retrieval uses vector search plus local lexical reranking.
- To enable native Qdrant dense+sparse fusion, set `QDRANT_ENABLE_NATIVE_SPARSE=true`, reset or create a fresh Qdrant collection, then reindex documents. Existing dense-only collections cannot store named sparse vectors without rebuilding.
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
