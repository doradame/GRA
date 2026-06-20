"""ID canonico stabile per le entita, condiviso tra tutti i percorsi che estraggono o
scrivono entita: GLiNER (gliner_extraction), estrazione relazioni LLM (extraction) e
scrittura nel grafo (graph_store).

Centralizzarlo qui evita il drift delle 3 copie identiche che c'erano prima (`_canonical_entity_id`
in gliner/extraction e `_normalize_entity_key` in graph_store): una modifica al formato
dell'ID in un solo modulo rompeva silenziosamente il join entita<->relazioni e creava
entita orfane nel grafo. Ora c'e un'unica fonte di verita.
"""
import hashlib


def canonical_entity_id(name: str, entity_type: str) -> str:
    """SHA256(normalized_type:normalized_name)[:32], case- e whitespace-insensitive.

    Stabile: stesso (name, type) -> stesso id, anche con case/whitespace diversi.
    Il tipo separa omonimi (es. "Milano" come Luogo vs Organizzazione).
    """
    normalized_name = " ".join(name.casefold().strip().split())
    normalized_type = " ".join(entity_type.casefold().strip().split()) or "unknown"
    return hashlib.sha256(f"{normalized_type}:{normalized_name}".encode("utf-8")).hexdigest()[:32]
