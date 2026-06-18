# Ingestion Pipeline

## Current Flow

1. Upload validates type and size, stores the original file in MinIO, and creates a `Document` in `uploaded`.
2. Celery starts `process_document()` with task metadata.
3. The pipeline creates or resumes an `IngestionJob`, cleans derived artifacts, then moves through `parsing`, `chunking`, `embedding`, `vector_indexing`, and `graph_indexing`.
4. Chunk IDs and Qdrant point IDs are deterministic, so retries rebuild instead of duplicating.
5. Qdrant payloads include `user_id`, `document_id`, `text_hash`, `token_count`, `section_title`, `char_start`, `char_end`, `page_start`, `page_end`, `document_page_count`, and status metadata.
6. Sparse vectors are computed with a BM25-like algorithm over the document's own chunk corpus.
7. Neo4j receives document, chunk, entity, and relation data after vector indexing succeeds:
   - **Entities** are extracted from **every chunk** using the local **GLiNER** NER model.
   - **Relations** are inferred by the LLM only for the first `MAX_RELATION_EXTRACTION_CHUNKS` chunks (default 48) to control API cost.

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
| `MAX_RELATION_EXTRACTION_CHUNKS` | `48` | Max chunks sent to the LLM for relation extraction |
| `MAX_GRAPH_EXTRACTION_CHUNKS` | `48` | Legacy fallback for relation chunk limit |

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
