import re
from dataclasses import dataclass
from typing import List, Tuple

import tiktoken


@dataclass(frozen=True)
class ChunkSpan:
    """Un chunk con i suoi offset assoluti nel testo originale.

    `text` è SEMPRE la slice esatta `original_text[start:end]`: questo invariant
    (garantito per construction qui sotto) rende le citazioni verificabili — un utente
    può aprire il documento a `start`/`end` e leggere esattamente `text`. Elimina la
    necessità di ricalcolare lo span a posteriori con `text.find(chunk)`, che prima
    falliva silenziosamente perché il chunk ricostruito non era una sottostringa esatta.
    """

    text: str
    start: int
    end: int


class _ApproxEncoding:
    def encode(self, text: str) -> List[str]:
        return text.split()


def _encoding_for_model(model: str):
    try:
        return tiktoken.encoding_for_model(model)
    except Exception:
        return _ApproxEncoding()


# Un'unità di chunking (paragrafo o frase): slice esatta del testo + offset assoluti.
_Unit = Tuple[str, int, int]


def _split_paragraphs(text: str) -> List[_Unit]:
    """Divide `text` in paragrafi sui separatori '\\n\\n', preservando gli offset assoluti.

    A differenza del vecchio `[p.strip() for p in text.split("\\n\\n") if p.strip()]`,
    NON fa strip: ogni unità è la slice esatta `text[start:end]` (esclusi i separatori),
    così la posizione nel documento resta verificabile. Le unità vuote/whitespace-only
    vengono scartate dall'accumulo ma gli offset delle unità significative restano coerenti.
    """
    units: List[_Unit] = []
    sep = "\n\n"
    start = 0
    pos = 0
    while True:
        idx = text.find(sep, pos)
        if idx == -1:
            seg = text[start:]
            units.append((seg, start, len(text)))
            break
        units.append((text[start:idx], start, idx))
        start = idx + len(sep)
        pos = start
    return [u for u in units if u[0].strip()]


def _split_sentences(unit: _Unit) -> List[_Unit]:
    """Splitta un paragrafo in frasi sui separatori '. ', preservando gli offset.

    Sostituisce il vecchio `para.replace('. ', '.\\n').split('\\n')` (che mutava il testo
    e rompeva la corrispondenza posizionale): qui si trovano le posizioni dei '. ' e si
    dividono in slice esatte consecutive. Ogni frase include il '. ' finale.
    """
    seg_text, seg_start, seg_end = unit
    sentences: List[_Unit] = []
    last = 0
    for m in re.finditer(r"\. ", seg_text):
        sentences.append((seg_text[last : m.end()], seg_start + last, seg_start + m.end()))
        last = m.end()
    if last < len(seg_text):
        sentences.append((seg_text[last:], seg_start + last, seg_end))
    return sentences or [unit]


def chunk_text(
    text: str,
    max_tokens: int = 512,
    overlap_tokens: int = 64,
    model: str = "text-embedding-3-large",
) -> List[ChunkSpan]:
    """Divide `text` in chunk, ognuno con offset assoluti (ChunkSpan).

    Il testo di ogni chunk è la slice esatta `text[start:end]` (include i separatori
    originali tra le unità accumulate), per cui `text[chunk.start:chunk.end] == chunk.text`
    vale sempre. Paragrafi > max_tokens vengono splittati in frasi. L'overlap riporta le
    ultime unità nel chunk successivo, retrocedendone lo start.
    """
    encoding = _encoding_for_model(model)
    paragraphs = _split_paragraphs(text)

    chunks: List[ChunkSpan] = []
    current: List[_Unit] = []
    current_len = 0

    def _close(units: List[_Unit]) -> None:
        # slice esatta che include i separatori originali tra la prima e l'ultima unità.
        start = units[0][1]
        end = units[-1][2]
        chunks.append(ChunkSpan(text=text[start:end], start=start, end=end))

    for unit in paragraphs:
        unit_tokens = len(encoding.encode(unit[0]))
        if unit_tokens > max_tokens:
            # Paragrafo troppo lungo: splitta in frasi e accumula quelle.
            for sent in _split_sentences(unit):
                sent_tokens = len(encoding.encode(sent[0]))
                if current_len + sent_tokens > max_tokens and current:
                    _close(current)
                    current, current_len = _apply_overlap(current, overlap_tokens)
                current.append(sent)
                current_len += sent_tokens
            continue

        if current_len + unit_tokens > max_tokens and current:
            _close(current)
            current, current_len = _apply_overlap(current, overlap_tokens)

        current.append(unit)
        current_len += unit_tokens

    if current:
        _close(current)

    return chunks


def _apply_overlap(units: List[_Unit], overlap_tokens: int) -> Tuple[List[_Unit], int]:
    """Riporta le ultime unità (sotto overlap_tokens) come seed del chunk successivo.

    Versione offset-aware del vecchio `_apply_overlap`: opera su `_Unit` (con offset)
    invece che su stringhe, così il chunk successivo retrocede lo start all'offset
    dell'unità di overlap e l'invariant `text[start:end]==chunk.text` si preserva.
    """
    encoding = _encoding_for_model("gpt-4")
    overlap: List[_Unit] = []
    overlap_len = 0
    for unit in reversed(units):
        part_len = len(encoding.encode(unit[0]))
        if overlap_len + part_len > overlap_tokens:
            break
        overlap.insert(0, unit)
        overlap_len += part_len
    return overlap, overlap_len
