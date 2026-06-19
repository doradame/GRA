from types import SimpleNamespace

from app.services.ingestion import (
    _build_chunk_embedding_input,
    _build_document_context,
    _find_chunk_span,
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


def test_chunk_span_and_page_mapping_helpers():
    text = "page one text\n\npage two text"
    start, end = _find_chunk_span(text, "page two", 0)

    assert text[start:end] == "page two"
    assert (start, end) == (15, 23)

    pages = [
        SimpleNamespace(page=1, start_char=0, end_char=13),
        SimpleNamespace(page=2, start_char=15, end_char=len(text)),
    ]
    assert _pages_for_span(pages, start, end) == (2, 2)


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
