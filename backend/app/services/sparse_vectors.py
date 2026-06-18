import hashlib
import logging
import math
from collections import Counter
from typing import Iterable

from qdrant_client.models import SparseVector

logger = logging.getLogger(__name__)

# Parametri BM25 standard. k1 controlla la saturazione della term-frequency,
# b controlla la normalizzazione per lunghezza del documento.
BM25_K1 = 1.5
BM25_B = 0.75
# Numero di bucket per l'hashing dei token. Deve essere coerente tra indexing e query.
BUCKETS = 1_000_003

# Cache lazy per i dati NLTK.
_NLTK_READY = False


def _ensure_nltk_data() -> None:
    """Scarica i dati NLTK necessari se non sono già presenti."""
    global _NLTK_READY
    if _NLTK_READY:
        return
    try:
        import nltk

        for resource in ("punkt", "stopwords"):
            try:
                nltk.data.find(f"tokenizers/{resource}" if resource == "punkt" else f"corpora/{resource}")
            except LookupError:
                logger.info("[sparse] Downloading NLTK resource: %s", resource)
                nltk.download(resource, quiet=True)
        _NLTK_READY = True
    except Exception as exc:
        logger.warning("[sparse] NLTK data unavailable: %s", exc)


def _tokenize(text: str) -> list[str]:
    """Tokenizza il testo per i vettori sparsi.

    Usa NLTK quando possibile, con fallback su regex semplice.
    Rimuove stopwords inglesi/italiane, punteggiatura e token corti.
    """
    _ensure_nltk_data()
    try:
        import nltk
        from nltk.corpus import stopwords

        stop_words = set(stopwords.words("italian")) | set(stopwords.words("english"))
        tokens = nltk.word_tokenize(text.lower())
    except Exception:
        # Fallback robusto se NLTK non è disponibile.
        stop_words = {
            "a", "ad", "agl", "agli", "ai", "al", "all", "alla", "alle", "allo", "anche",
            "are", "che", "chi", "ci", "coi", "col", "come", "con", "contro", "da", "dagl",
            "dagli", "dai", "dal", "dall", "dalla", "dalle", "dallo", "degl", "degli", "dei",
            "del", "dell", "della", "delle", "dello", "di", "e", "ed", "egli", "ella", "esso",
            "fur", "gli", "ha", "hai", "hanno", "ho", "i", "il", "in", "io", "l", "la", "le",
            "li", "lo", "ma", "me", "mi", "mia", "mie", "miei", "mio", "ne", "negl", "negli",
            "nei", "nel", "nell", "nella", "nelle", "nello", "noi", "non", "nostri", "nostro",
            "o", "od", "per", "poi", "qua", "quale", "quanta", "quante", "quanti", "quanto",
            "quel", "quella", "quelle", "quelli", "quest", "questa", "queste", "questi", "questo",
            "qui", "se", "sei", "si", "sia", "siamo", "siete", "sono", "su", "sua", "sue", "sugl",
            "sugli", "sui", "sul", "sull", "sulla", "sulle", "sullo", "suo", "suoi", "ti", "tra",
            "tu", "tua", "tue", "tuo", "tuoi", "tutti", "tutto", "un", "una", "uno", "vi", "voi",
            "vostri", "vostro", "the", "and", "for", "are", "but", "not", "you", "all", "can",
            "had", "her", "was", "one", "our", "out", "day", "get", "has", "him", "his", "how",
            "its", "may", "new", "now", "old", "see", "two", "who", "boy", "did", "she", "use",
            "her", "way", "many", "oil", "sit", "set", "run", "eat", "far", "sea", "eye", "ago",
            "off", "too", "any", "say", "man", "try", "ask", "end", "why", "let", "put", "say",
            "she", "try", "way", "own", "say", "too", "old", "tell", "very", "when", "much", "would",
        }
        tokens = [t for t in text.lower().split() if t]

    filtered: list[str] = []
    for token in tokens:
        # Rimuovi punteggiatura ai bordi e filtra token non alfabetici/corti.
        punctuation_marks = '.,;:!?()[]{}' + '"' + '«»–—-'
        clean = token.strip(punctuation_marks).strip()
        if len(clean) >= 3 and clean.isalpha() and clean not in stop_words:
            filtered.append(clean)
    return filtered


def _hash_token(token: str, buckets: int = BUCKETS) -> int:
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % buckets


def _compute_bm25_weights(
    tokens: list[str],
    corpus_tokens: list[list[str]],
    k1: float = BM25_K1,
    b: float = BM25_B,
) -> dict[str, float]:
    """Calcola i pesi BM25 per i token di un documento rispetto a un corpus.

    Se il corpus è vuoto o monodocumentale, il componente IDF viene neutralizzato
    a 1.0 in modo da non penalizzare termini comuni.
    """
    if not tokens:
        return {}

    N = len(corpus_tokens)
    avgdl = sum(len(doc) for doc in corpus_tokens) / max(N, 1)
    doc_len = len(tokens)
    tf = Counter(tokens)

    # Pre-calcola document frequency per ogni termine del documento corrente.
    dfs = {
        term: sum(1 for doc in corpus_tokens if term in doc)
        for term in tf.keys()
    }

    weights: dict[str, float] = {}
    for term, freq in tf.items():
        df = dfs.get(term, 0)
        if N > 1 and df > 0:
            idf = math.log((N - df + 0.5) / (df + 0.5) + 1.0)
        else:
            idf = 1.0
        denom = freq + k1 * (1.0 - b + b * (doc_len / max(avgdl, 1.0)))
        weights[term] = idf * (freq * (k1 + 1.0)) / denom
    return weights


def build_sparse_vector(
    text: str,
    corpus_tokens: list[list[str]] | None = None,
    buckets: int = BUCKETS,
) -> SparseVector:
    """Costruisce un vettore sparso BM25-like per Qdrant.

    Args:
        text: il testo da vettorializzare (chunk durante l'indexing, query durante il retrieval).
        corpus_tokens: lista di documenti tokenizzati che costituiscono il corpus per l'IDF.
            Durante l'ingestion questo sarà la lista di tutti i chunk del documento;
            durante il retrieval può essere None (viene usato solo TF pesato).
    """
    tokens = _tokenize(text)
    if not tokens:
        return SparseVector(indices=[], values=[])

    weights = _compute_bm25_weights(tokens, corpus_tokens or [tokens])
    if not weights:
        return SparseVector(indices=[], values=[])

    # Applichiamo hashing ai token per ottenere indici sparsi compatibili con Qdrant.
    weighted: dict[int, float] = {}
    for term, weight in weights.items():
        index = _hash_token(term, buckets)
        weighted[index] = weighted.get(index, 0.0) + weight

    # Normalizzazione L2 per rendere il vettore comparable con quello denso.
    norm = math.sqrt(sum(value * value for value in weighted.values()))
    if norm > 0:
        weighted = {index: value / norm for index, value in weighted.items()}

    items = sorted(weighted.items())
    return SparseVector(
        indices=[index for index, _ in items],
        values=[value for _, value in items],
    )


def tokenize_sparse(text: str) -> list[str]:
    """Esporta la tokenizzazione per eventuali altri moduli (es. corpus construction)."""
    return _tokenize(text)
