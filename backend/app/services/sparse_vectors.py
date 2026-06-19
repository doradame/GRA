import logging
import math
from collections import Counter

from qdrant_client.models import SparseVector

from app.services.sparse_corpus_stats import get_global_stats_snapshot, get_term_ids_cached

logger = logging.getLogger(__name__)

# Parametri BM25 standard. k1 controlla la saturazione della term-frequency,
# b controlla la normalizzazione per lunghezza del documento.
BM25_K1 = 1.5
BM25_B = 0.75

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


def weighted_sparse_vector(
    tokens: list[str],
    term_id_map: dict[str, int],
    global_df: dict[int, int],
    total_chunks: int,
    avg_doc_len: float,
    k1: float = BM25_K1,
    b: float = BM25_B,
) -> SparseVector:
    """Calcola i pesi BM25 di un testo già tokenizzato usando id di vocabolario stabili
    (niente hashing/collisioni) e IDF calcolata sull'intero corpus indicizzato finora, non
    solo sul singolo documento.

    Termini non presenti in term_id_map (mai visti in indexing, possibile solo a query-time)
    vengono ignorati: non possono comunque corrispondere a nessun chunk indicizzato.
    """
    if not tokens:
        return SparseVector(indices=[], values=[])

    doc_len = len(tokens)
    tf = Counter(tokens)

    weighted: dict[int, float] = {}
    for term, freq in tf.items():
        term_id = term_id_map.get(term)
        if term_id is None:
            continue
        df = global_df.get(term_id, 0)
        idf = math.log((total_chunks - df + 0.5) / (df + 0.5) + 1.0) if total_chunks > 0 else math.log(2.0)
        denom = freq + k1 * (1.0 - b + b * (doc_len / max(avg_doc_len, 1.0)))
        weight = idf * (freq * (k1 + 1.0)) / denom
        if weight > 0:
            weighted[term_id] = weighted.get(term_id, 0.0) + weight

    # Normalizzazione L2 per rendere il vettore comparabile con quello denso.
    norm = math.sqrt(sum(value * value for value in weighted.values()))
    if norm > 0:
        weighted = {index: value / norm for index, value in weighted.items()}

    items = sorted(weighted.items())
    return SparseVector(
        indices=[index for index, _ in items],
        values=[value for _, value in items],
    )


def build_query_sparse_vector(text: str) -> SparseVector:
    """Costruisce il vettore sparso di una query a retrieval-time.

    Nessuna scrittura: legge solo la cache Redis del vocabolario e le statistiche globali
    correnti (niente sessione DB necessaria in questo percorso, sincrono). I termini della
    query mai visti in indexing vengono ignorati (get_term_ids_cached li omette).
    """
    tokens = _tokenize(text)
    term_ids = get_term_ids_cached(tokens)
    df, total_chunks, avg_doc_len = get_global_stats_snapshot(term_ids.values())
    return weighted_sparse_vector(tokens, term_ids, df, total_chunks, avg_doc_len)


def tokenize_sparse(text: str) -> list[str]:
    """Esporta la tokenizzazione per eventuali altri moduli (es. corpus construction)."""
    return _tokenize(text)
