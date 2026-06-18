import re
from typing import List

from app.core.config import get_settings

settings = get_settings()


def format_reference(payload: dict) -> str:
    filename = payload.get("filename") or "documento"
    parts = [str(filename)]
    page_start = payload.get("page_start")
    page_end = payload.get("page_end")
    if isinstance(page_start, int):
        if isinstance(page_end, int) and page_end != page_start:
            parts.append(f"pagine {page_start}-{page_end}")
        else:
            parts.append(f"pagina {page_start}")
    elif payload.get("section_title"):
        parts.append(f"sezione: {payload.get('section_title')}")
    elif isinstance(payload.get("index"), int):
        parts.append(f"parte {payload.get('index') + 1}")
    return ", ".join(parts)


def extract_quote(text: str, max_chars: int = 320) -> str:
    clean = re.sub(r"\s+", " ", str(text)).strip()
    if len(clean) <= max_chars:
        return clean
    excerpt = clean[:max_chars].rsplit(" ", 1)[0].rstrip(".,;:")
    return f"{excerpt}..."


def token_set(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[\wÀ-ÿ]{3,}", text.casefold())
        if token not in {"the", "and", "for", "con", "per", "che", "del", "della", "gli", "una"}
    }


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def rerank_hybrid(query: str, results: List[dict]) -> List[dict]:
    query_tokens = token_set(query)
    weight = min(max(settings.retrieval_lexical_weight, 0.0), 1.0)
    if not query_tokens or weight == 0:
        return results

    reranked = []
    for result in results:
        text = str(result.get("payload", {}).get("text", ""))
        lexical_score = jaccard(query_tokens, token_set(text))
        vector_score = float(result.get("score", 0.0))
        combined = (vector_score * (1 - weight)) + (lexical_score * weight)
        enriched = dict(result)
        enriched["hybrid_score"] = combined
        enriched["lexical_score"] = lexical_score
        reranked.append(enriched)
    return sorted(reranked, key=lambda item: item["hybrid_score"], reverse=True)


def diversify_results(results: List[dict], max_similarity: float = 0.82) -> List[dict]:
    selected: List[dict] = []
    selected_tokens: List[set[str]] = []

    for result in results:
        text = str(result.get("payload", {}).get("text", ""))
        tokens = token_set(text)
        if not tokens:
            selected.append(result)
            selected_tokens.append(tokens)
            continue
        if all(jaccard(tokens, existing) <= max_similarity for existing in selected_tokens):
            selected.append(result)
            selected_tokens.append(tokens)

    return selected
