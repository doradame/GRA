from typing import List
import tiktoken


class _ApproxEncoding:
    def encode(self, text: str) -> List[str]:
        return text.split()


def _encoding_for_model(model: str):
    try:
        return tiktoken.encoding_for_model(model)
    except Exception:
        return _ApproxEncoding()


def chunk_text(
    text: str,
    max_tokens: int = 512,
    overlap_tokens: int = 64,
    model: str = "text-embedding-3-large",
) -> List[str]:
    encoding = _encoding_for_model(model)
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: List[str] = []
    current: List[str] = []
    current_len = 0

    for para in paragraphs:
        para_tokens = len(encoding.encode(para))
        if para_tokens > max_tokens:
            # dividi paragrafi troppo lunghi per frasi
            sentences = para.replace(". ", ".\n").split("\n")
            for sent in sentences:
                sent_tokens = len(encoding.encode(sent))
                if current_len + sent_tokens > max_tokens and current:
                    chunks.append("\n\n".join(current))
                    current, current_len = _apply_overlap(current, overlap_tokens)
                current.append(sent)
                current_len += sent_tokens
            continue

        if current_len + para_tokens > max_tokens and current:
            chunks.append("\n\n".join(current))
            current, current_len = _apply_overlap(current, overlap_tokens)

        current.append(para)
        current_len += para_tokens

    if current:
        chunks.append("\n\n".join(current))

    return chunks


def _apply_overlap(parts: List[str], overlap_tokens: int):
    encoding = _encoding_for_model("gpt-4")
    overlap: List[str] = []
    overlap_len = 0
    for part in reversed(parts):
        part_len = len(encoding.encode(part))
        if overlap_len + part_len > overlap_tokens:
            break
        overlap.insert(0, part)
        overlap_len += part_len
    return overlap, overlap_len
