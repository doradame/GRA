from types import SimpleNamespace

from app.services.chunking import ChunkSpan, chunk_text
from app.services.ingestion import _pages_for_span


def test_single_chunk_covers_whole_text():
    text = "Breve paragrafo.\n\nAltro paragrafo breve."
    chunks = chunk_text(text, max_tokens=512)

    assert len(chunks) == 1
    assert chunks[0].start == 0
    assert chunks[0].end == len(text)
    # invariant: la slice esatta coincide col testo del chunk.
    assert text[chunks[0].start : chunks[0].end] == chunks[0].text


def test_invariant_holds_for_every_chunk():
    # max_tokens piccolo per forzare piu chunk su testo con piu paragrafi.
    para = "Questo e un paragrafo di prova con diverse parole. " * 8
    text = "\n\n".join([para, para, para, para])
    chunks = chunk_text(text, max_tokens=60, overlap_tokens=0)

    assert len(chunks) >= 2
    for chunk in chunks:
        assert text[chunk.start : chunk.end] == chunk.text
    starts = [c.start for c in chunks]
    assert starts == sorted(starts)
    assert chunks[0].start == 0


def test_overlap_makes_chunks_overlap_and_keeps_invariant():
    text = "Frase uno. Frase due. Frase tre. Frase quattro. Frase cinque. " * 6
    chunks = chunk_text(text, max_tokens=40, overlap_tokens=20)

    assert len(chunks) >= 2
    for chunk in chunks:
        assert text[chunk.start : chunk.end] == chunk.text
    # con overlap, lo start del chunk successivo precede l'end del precedente.
    assert chunks[1].start < chunks[0].end


def test_long_paragraph_split_into_sentences_keeps_invariant():
    # Unico paragrafo lunghissimo (nessun '\n\n') con molte frasi.
    text = "Questa e una frase. " * 60
    chunks = chunk_text(text, max_tokens=30, overlap_tokens=0)

    assert len(chunks) >= 2
    for chunk in chunks:
        assert text[chunk.start : chunk.end] == chunk.text


def test_single_unit_larger_than_max_tokens_becomes_one_chunk():
    # Nessun '. ' ne '\n\n': una sola unita che sfora max_tokens -> 1 chunk che la contiene.
    text = "parola" * 200
    chunks = chunk_text(text, max_tokens=10)

    assert len(chunks) >= 1
    for chunk in chunks:
        assert text[chunk.start : chunk.end] == chunk.text
    assert chunks[0].start == 0
    assert chunks[-1].end == len(text)


def test_empty_and_whitespace_only_text_produces_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   \n\n  \n\n ") == []


def test_chunk_spans_map_to_pdf_pages():
    # Simula parsing._extract_pdf: paghe join '\n\n' con cursor += len + 2.
    parts = ["Prima pagina testo.", "Seconda pagina testo.", "Terza pagina testo."]
    text = "\n\n".join(parts)
    pages = []
    cursor = 0
    for i, p in enumerate(parts, start=1):
        pages.append(SimpleNamespace(page=i, start_char=cursor, end_char=cursor + len(p)))
        cursor += len(p) + 2

    # max_tokens alto -> 1 chunk che copre tutto -> tocca tutte e 3 le pagine.
    chunks = chunk_text(text, max_tokens=2000)
    assert len(chunks) == 1
    assert _pages_for_span(pages, chunks[0].start, chunks[0].end) == (1, 3)


def test_chunk_span_is_frozen_dataclass():
    chunk = ChunkSpan(text="abc", start=0, end=3)
    assert chunk.text == "abc"
    assert (chunk.start, chunk.end) == (0, 3)
