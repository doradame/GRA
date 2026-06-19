import logging
import math
from collections import defaultdict
from typing import Any

import numpy as np

from app.core.config import get_settings
from app.services.embeddings import embed_texts
from app.services.graph_store import graph_store

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 0.93
DEFAULT_BATCH_SIZE = 64

# Cypher di merge di due entità: fonde `other_id` nel `canonical_id` preservando
# relazioni e proprietà. Eseguito in batch dentro una singola transazione per gruppo
# (vedi resolve_entities) così un fallimento a metà gruppo fa rollback dell'intero
# gruppo invece di lasciare entità parzialmente fuse.
_MERGE_ENTITIES_CYPHER = """
MATCH (a:Entity {id: $canonical_id})
MATCH (b:Entity {id: $other_id})
WITH [a, b] AS nodes
CALL apoc.refactor.mergeNodes(nodes, {
    properties: 'combine',
    mergeRels: true,
    preserveExistingProperties: true
})
YIELD node
SET node.id = $canonical_id
RETURN node.id AS id
"""


class _UnionFind:
    """Union-Find semplice per raggruppare entità da fondere."""

    def __init__(self, items: list[str]):
        self.parent = {item: item for item in items}

    def find(self, item: str) -> str:
        # Path compression
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, a: str, b: str) -> None:
        root_a = self.find(a)
        root_b = self.find(b)
        if root_a != root_b:
            # Unione per ordine lessicografico stabile.
            self.parent[root_b] = root_a


def _cosine_similarity_matrix(vectors: np.ndarray) -> np.ndarray:
    """Calcola la matrice di similarità del coseno tra vettori riga."""
    # Normalizza i vettori per righe.
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0  # Evita divisione per zero.
    normalized = vectors / norms
    return np.dot(normalized, normalized.T)


def _pick_canonical_id(entities: list[dict[str, Any]]) -> str:
    """Sceglie l'ID canonico per un gruppo di entità.

    Preferisce nomi più corti (tipicamente più canonici) e, a parità di lunghezza,
    ordine alfabetico per stabilità.
    """
    sorted_entities = sorted(entities, key=lambda e: (len(str(e["name"])), str(e["id"])))
    return sorted_entities[0]["id"]


async def resolve_entities(
    threshold: float = DEFAULT_THRESHOLD,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, int]:
    """Esegue la entity resolution fuzzy sul grafo Neo4j.

    Per ogni tipo di entità, calcola gli embedding dei nomi, trova coppie con
    similarità del coseno superiore a `threshold` e le fonde tramite
    `apoc.refactor.mergeNodes` preservando relazioni e proprietà.

    Returns:
        Statistiche dell'operazione: numero di entità esaminate, gruppi fusi,
        entità rimosse.
    """
    logger.info("[entity_resolution] Starting entity resolution (threshold=%s)", threshold)

    with graph_store.driver.session() as session:
        result = session.run(
            """
            MATCH (e:Entity)
            RETURN e.id AS id, e.name AS name, e.type AS type
            """
        )
        records = [dict(record) for record in result]

    if not records:
        logger.info("[entity_resolution] No entities to resolve")
        return {"examined": 0, "merged_groups": 0, "removed_entities": 0}

    logger.info("[entity_resolution] Loaded %s entities", len(records))

    # Raggruppa per tipo; la similarità ha senso confrontare entità omogenee.
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_type[str(record.get("type") or "Unknown")].append(record)

    removed_count = 0
    merged_groups = 0

    for entity_type, entities in by_type.items():
        if len(entities) < 2:
            continue

        logger.info(
            "[entity_resolution] Processing type=%s with %s entities",
            entity_type,
            len(entities),
        )

        names = [str(e.get("name") or e["id"]) for e in entities]
        embeddings: list[list[float]] = []
        for start in range(0, len(names), batch_size):
            batch = names[start : start + batch_size]
            embeddings.extend(await embed_texts(batch))

        expected_dim = get_settings().embedding_dimensions
        matrix = np.array(embeddings, dtype=np.float32)
        if matrix.shape[1] != expected_dim:
            logger.warning(
                "[entity_resolution] Embedding dimension mismatch for type=%s: got %s, expected %s",
                entity_type,
                matrix.shape[1],
                expected_dim,
            )

        sim_matrix = _cosine_similarity_matrix(matrix)
        ids = [e["id"] for e in entities]
        uf = _UnionFind(ids)

        # Trova coppie sopra soglia (triangolo superiore, esclusa diagonale).
        n = len(entities)
        for i in range(n):
            for j in range(i + 1, n):
                score = float(sim_matrix[i, j])
                if score > threshold:
                    logger.debug(
                        "[entity_resolution] Similar pair (score=%.4f): %s ~ %s",
                        score,
                        names[i],
                        names[j],
                    )
                    uf.union(ids[i], ids[j])

        # Costruisci i gruppi.
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for entity in entities:
            groups[uf.find(entity["id"])].append(entity)

        for root_id, group in groups.items():
            if len(group) < 2:
                continue

            canonical_id = _pick_canonical_id(group)
            other_ids = [e["id"] for e in group if e["id"] != canonical_id]
            if not other_ids:
                continue
            logger.info(
                "[entity_resolution] Merging group of %s entities into canonical=%s (%s)",
                len(group),
                canonical_id,
                next((e["name"] for e in group if e["id"] == canonical_id), ""),
            )

            # Tutto il gruppo in UNA transazione Neo4j: se un merge fallisce il gruppo
            # resta non fuso (rollback) invece di parzialmente fuso. Il merge non è
            # idempotente di per sé, ma il lock distribuito + retry disabilitato nel
            # task impediscono re-run sovrapposti che aggraverebbero un fallimento.
            try:
                with graph_store.driver.session() as session:
                    with session.begin_transaction() as tx:
                        for other_id in other_ids:
                            tx.run(
                                _MERGE_ENTITIES_CYPHER,
                                canonical_id=canonical_id,
                                other_id=other_id,
                            )
                removed_count += len(other_ids)
                merged_groups += 1
            except Exception as exc:
                logger.exception(
                    "[entity_resolution] Failed to merge group of %s into canonical=%s: %s",
                    len(other_ids),
                    canonical_id,
                    exc,
                )

    logger.info(
        "[entity_resolution] Completed: examined=%s merged_groups=%s removed_entities=%s",
        len(records),
        merged_groups,
        removed_count,
    )
    return {
        "examined": len(records),
        "merged_groups": merged_groups,
        "removed_entities": removed_count,
    }
