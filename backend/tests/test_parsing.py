from app.services.parsing import _render_markdown_table, extract_document


def _build_minimal_pdf(text: str) -> bytes:
    """Costruisce un PDF minimo valido (un'unica pagina di testo) senza dipendenze esterne."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> "
        b"/MediaBox [0 0 200 200] /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    content = f"BT /F1 24 Tf 10 100 Td ({text}) Tj ET".encode()
    objects.append(b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream")

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_offset = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += b"trailer\n"
    out += f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode()
    out += b"startxref\n"
    out += f"{xref_offset}\n".encode()
    out += b"%%EOF"
    return bytes(out)


def test_extract_document_returns_structured_text_result():
    result = extract_document("notes.txt", b"hello\nworld")

    assert result.text == "hello\nworld"
    assert result.parser == "text"
    assert result.ocr_used is False


def test_extract_document_uses_text_fallback_for_unknown_binary():
    result = extract_document("unknown.bin", b"\x00\x01plain enough")

    assert "plain enough" in result.text
    assert result.parser == "text_fallback"


def test_extract_document_parses_pdf_text_with_pdfplumber():
    pdf_bytes = _build_minimal_pdf("Hello PDF")
    result = extract_document("report.pdf", pdf_bytes)

    assert result.parser == "pdfplumber"
    assert result.page_count == 1
    assert "Hello PDF" in result.text
    assert result.pages is not None
    assert result.pages[0].page == 1


def _build_pdf_with_grid_table() -> bytes:
    """PDF minimo con una vera tabella 2x2 delimitata da linee disegnate (non solo testo allineato)."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> "
        b"/MediaBox [0 0 200 200] /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    content = b"\n".join(
        [
            b"50 150 m 150 150 l S",
            b"50 100 m 150 100 l S",
            b"50 50 m 150 50 l S",
            b"50 50 m 50 150 l S",
            b"100 50 m 100 150 l S",
            b"150 50 m 150 150 l S",
            b"BT /F1 10 Tf 60 130 Td (A1) Tj ET",
            b"BT /F1 10 Tf 110 130 Td (B1) Tj ET",
            b"BT /F1 10 Tf 60 80 Td (A2) Tj ET",
            b"BT /F1 10 Tf 110 80 Td (B2) Tj ET",
        ]
    )
    objects.append(b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream")

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_offset = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += b"trailer\n"
    out += f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode()
    out += b"startxref\n"
    out += f"{xref_offset}\n".encode()
    out += b"%%EOF"
    return bytes(out)


def test_extract_document_renders_a_real_ruled_table_as_markdown():
    pdf_bytes = _build_pdf_with_grid_table()
    result = extract_document("report.pdf", pdf_bytes)

    assert "Tabella 1:" in result.text
    assert "| A1 | B1 |" in result.text
    assert "| A2 | B2 |" in result.text


def test_extract_document_does_not_misdetect_plain_prose_as_a_table():
    # Testo libero senza alcuna linea disegnata: con la strategia di default ("text"),
    # pdfplumber può inferire colonne fantasma dalla sola posizione del testo. Usando
    # lines_strict (richiede linee di confine reali) questo falso positivo va evitato.
    pdf_bytes = _build_minimal_pdf("Hello PDF")
    result = extract_document("report.pdf", pdf_bytes)

    assert "Tabella" not in result.text
    assert "|" not in result.text


def test_render_markdown_table_builds_header_and_rows():
    rows = [["Sistema", "Uptime %"], ["Firewall DMZ", "99.95"], [None, "0"]]

    rendered = _render_markdown_table(rows)

    assert rendered == (
        "| Sistema | Uptime % |\n"
        "| --- | --- |\n"
        "| Firewall DMZ | 99.95 |\n"
        "|  | 0 |"
    )


def test_render_markdown_table_escapes_pipes_and_skips_blank_rows():
    rows = [["A", "B"], ["", ""], ["x|y", "line\nbreak"]]

    rendered = _render_markdown_table(rows)

    assert rendered == (
        "| A | B |\n"
        "| --- | --- |\n"
        "| x\\|y | line break |"
    )


def test_render_markdown_table_returns_empty_string_for_no_content():
    assert _render_markdown_table([]) == ""
    assert _render_markdown_table([[None, None], ["", ""]]) == ""
