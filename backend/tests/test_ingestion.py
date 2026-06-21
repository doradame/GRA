import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.ingestion import (
    STATUS_ERROR,
    _build_chunk_embedding_input,
    _build_document_context,
    _handle_ingestion_error,
    _infer_section_title,
    _pages_for_span,
    _safe_filename,
    _stable_uuid,
    _token_count,
)


def test_stable_uuid_is_deterministic_and_changes_with_parts():
    first = _stable_uuid("chunk", "doc-1", 0, "hash")
    second = _stable_uuid("chunk", "doc-1", 0, "hash")
    different = _stable_uuid("chunk", "doc-1", 1, "hash")

    assert first == second
    assert first != different


def test_safe_filename_removes_paths_and_unsafe_characters():
    assert _safe_filename("../nested/bad:file?.pdf") == "bad_file_.pdf"
    assert _safe_filename("") == "unnamed"


def test_token_count_and_section_title_helpers():
    assert _token_count("hello world", "text-embedding-3-large") > 0
    assert _infer_section_title("TERMS AND CONDITIONS\n\nBody text.") == "TERMS AND CONDITIONS"
    assert _infer_section_title("This is a normal sentence.") is None


def test_pages_for_span_maps_chunk_to_page_range():
    text = "page one text\n\npage two text"
    pages = [
        SimpleNamespace(page=1, start_char=0, end_char=13),
        SimpleNamespace(page=2, start_char=15, end_char=len(text)),
    ]

    # Chunk interamente nella pagina 2.
    assert _pages_for_span(pages, 15, 23) == (2, 2)
    # Chunk a cavallo del separatore tra pagina 1 e 2.
    assert _pages_for_span(pages, 10, 20) == (1, 2)
    # Nessuna pagina (formato non-PDF) -> (None, None).
    assert _pages_for_span(None, 0, 10) == (None, None)


def test_build_document_context_includes_only_provided_fields():
    full = _build_document_context("manuale.pdf", "Manualistica tecnica", "Guida operativa per il personale")
    assert full == "Documento: manuale.pdf\nCategoria: Manualistica tecnica\nDescrizione: Guida operativa per il personale"

    minimal = _build_document_context("manuale.pdf", None, None)
    assert minimal == "Documento: manuale.pdf"


def test_build_chunk_embedding_input_prepends_context_and_section():
    context = "Documento: manuale.pdf\nCategoria: Manualistica tecnica"
    with_section = _build_chunk_embedding_input(context, "CONDIZIONI GENERALI", "Testo del chunk.")
    assert with_section == "Documento: manuale.pdf\nCategoria: Manualistica tecnica\n\nSezione: CONDIZIONI GENERALI\n\nTesto del chunk."

    without_section = _build_chunk_embedding_input(context, None, "Testo del chunk.")
    assert without_section == "Documento: manuale.pdf\nCategoria: Manualistica tecnica\n\nTesto del chunk."


def test_build_chunk_embedding_input_includes_llm_context_when_present():
    context = "Documento: manuale.pdf"

    with_llm_context = _build_chunk_embedding_input(
        context, "CONDIZIONI GENERALI", "Testo del chunk.", "Il chunk descrive le condizioni del contratto X."
    )
    assert with_llm_context == (
        "Documento: manuale.pdf\n\n"
        "Sezione: CONDIZIONI GENERALI\n\n"
        "Il chunk descrive le condizioni del contratto X.\n\n"
        "Testo del chunk."
    )

    with_empty_llm_context = _build_chunk_embedding_input(context, None, "Testo del chunk.", "")
    assert with_empty_llm_context == "Documento: manuale.pdf\n\nTesto del chunk."


def test_handle_ingestion_error_aborts_cleanly_when_document_deleted():
    # Documento cancellato concorrentemente: la query di esistenza post-rollback torna None
    # -> uscita pulita (False), nessun cleanup Qdrant/Neo4j, nessun merge/commit, nessun retry.
    db = AsyncMock()
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = None
    db.execute.return_value = scalar_result

    with patch("app.services.ingestion._cleanup_document_artifacts", new=AsyncMock()) as cleanup:
        should_raise = asyncio.run(
            _handle_ingestion_error(db, "doc-1", MagicMock(), MagicMock(), RuntimeError("boom"))
        )

    assert should_raise is False
    db.rollback.assert_awaited_once()
    cleanup.assert_not_called()
    db.merge.assert_not_called()
    db.commit.assert_not_called()


def test_handle_ingestion_error_marks_error_and_propagates_when_document_exists():
    # Documento ancora presente: comportamento storico -> cleanup, mark error su doc+job,
    # commit, ritorna True (propaga -> retry Celery).
    db = AsyncMock()
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = MagicMock()
    db.execute.return_value = scalar_result

    merged = MagicMock()
    merged_job = MagicMock()
    db.merge.side_effect = [merged, merged_job]

    with patch("app.services.ingestion._cleanup_document_artifacts", new=AsyncMock()) as cleanup:
        should_raise = asyncio.run(
            _handle_ingestion_error(db, "doc-1", MagicMock(), MagicMock(), RuntimeError("boom"))
        )

    assert should_raise is True
    db.rollback.assert_awaited_once()
    cleanup.assert_awaited_once_with(db, "doc-1")
    assert db.merge.await_count == 2
    db.commit.assert_awaited_once()
    assert merged.status == STATUS_ERROR
    assert merged.error_message == "boom"
    assert merged_job.status == STATUS_ERROR
    assert merged_job.error_code == "RuntimeError"
    assert merged_job.progress == 100
