import hashlib
import math
import re
from collections import Counter

from qdrant_client.models import SparseVector

STOPWORDS = {
    "and",
    "are",
    "che",
    "con",
    "del",
    "della",
    "for",
    "gli",
    "nel",
    "per",
    "the",
    "una",
}


def tokenize_sparse(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[\wÀ-ÿ]{3,}", text.casefold())
        if token not in STOPWORDS
    ]


def build_sparse_vector(text: str, buckets: int = 1_000_003) -> SparseVector:
    counts = Counter(tokenize_sparse(text))
    if not counts:
        return SparseVector(indices=[], values=[])

    weighted: dict[int, float] = {}
    for token, count in counts.items():
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest, "big") % buckets
        weighted[index] = weighted.get(index, 0.0) + (1.0 + math.log(count))

    norm = math.sqrt(sum(value * value for value in weighted.values()))
    if norm > 0:
        weighted = {index: value / norm for index, value in weighted.items()}

    items = sorted(weighted.items())
    return SparseVector(
        indices=[index for index, _ in items],
        values=[value for _, value in items],
    )
