from app.services.ingestion import _infer_section_title, _safe_filename, _stable_uuid, _token_count


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
