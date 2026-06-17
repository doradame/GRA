from app.services.parsing import extract_document


def test_extract_document_returns_structured_text_result():
    result = extract_document("notes.txt", b"hello\nworld")

    assert result.text == "hello\nworld"
    assert result.parser == "text"
    assert result.ocr_used is False


def test_extract_document_uses_text_fallback_for_unknown_binary():
    result = extract_document("unknown.bin", b"\x00\x01plain enough")

    assert "plain enough" in result.text
    assert result.parser == "text_fallback"
