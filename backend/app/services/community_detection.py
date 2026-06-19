import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import networkx as nx
from openai import AsyncOpenAI

from app.core.config import get_settings
from app.services.graph_store import graph_store

settings = get_settings()
client = AsyncOpenAI(api_key=settings.openai_api_key)
logger = logging.getLogger(__name__)


SUMMARY_PROMPT = """Sei un assistente specializzato in analisi di grafi di conoscenza.
Ti fornisco un insieme di entità e relazioni che formano una community (cluster) all'interno di una knowledge base estratta da documenti.

Genera un riassunto conciso in italiano (massimo 3-4 frasi) che descriva:
- Qual è l'argomento principale della community.
- Quali entità sono coinvolte.
- Quali relazioni le legano.

Entità ({entity_count}):
{entities_text}

Relazioni interne ({relation_count}):
{relations_text}

Riassunto:"""


def _build_entity_graph() -> Tuple[nx.Graph, Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    """Legge entità e relazioni da Neo4j e restituisce grafo non diretto + metadati."""
    G = nx.Graph()
    entities: Dict[str, Dict[str, Any]] = {}
    relations: List[Dict[str, Any]] = []

    with graph_store.driver.session() as session:
        # Leggi entità
        entity_result = session.run(
            "MATCH (e:Entity) RETURN e.id AS id, e.name AS name, e.type AS type"
        )
        for record in entity_result:
            entity_id = record.get("id")
            if not entity_id:
                continue
            entities[entity_id] = {
                "id": entity_id,
                "name": graph_store._stringify_name(record.get("name")),
                "type": record.get("type", "Unknown"),
            }
            G.add_node(entity_id)

        # Leggi relazioni tra entità (escludi MENTIONS e BELONGS_TO_COMMUNITY)
        rel_result = session.run(
            """
            MATCH (s:Entity)-[r]->(t:Entity)
            WHERE type(r) <> 'MENTIONS' AND type(r) <> 'BELONGS_TO_COMMUNITY'
            RETURN s.id AS source_id, t.id AS target_id, type(r) AS rel_type
            """
        )
        for record in rel_result:
            source_id = record.get("source_id")
            target_id = record.get("target_id")
            if not source_id or not target_id:
                continue
            rel = {
                "source_id": source_id,
                "target_id": target_id,
                "type": record.get("rel_type", "RELATED_TO"),
            }
            relations.append(rel)
            G.add_edge(source_id, target_id, type=rel["type"])

    logger.info("[community_detection] Grafo caricato: %s nodi, %s archi", G.number_of_nodes(), G.number_of_edges())
    return G, entities, relations


def _detect_communities(G: nx.Graph, algorithm: str, resolution: float) -> Dict[str, int]:
    if G.number_of_nodes() == 0:
        return {}
    if algorithm == "louvain":
        import community as community_louvain
        return community_louvain.best_partition(G, resolution=resolution, random_state=42)
    raise ValueError(f"Algoritmo di community detection non supportato: {algorithm}")


def _detect_root_communities(G: nx.Graph, algorithm: str, resolution: float) -> Dict[str, int]:
    """Livello più aggregato della gerarchia di Louvain (poche community ampie, l'intero
    grafo). Usato per riassunti "globali" su tutto il KB, separati dalle community a grana
    fine di _detect_communities (utili invece per domande più localizzate)."""
    if G.number_of_nodes() == 0:
        return {}
    if algorithm != "louvain":
        raise ValueError(f"Algoritmo di community detection non supportato: {algorithm}")
    import community as community_louvain
    dendrogram = community_louvain.generate_dendrogram(G, resolution=resolution, random_state=42)
    top_level = len(dendrogram) - 1
    return community_louvain.partition_at_level(dendrogram, top_level)


def _group_by_community(partition: Dict[str, int]) -> Dict[int, List[str]]:
    grouped: Dict[int, List[str]] = {}
    for entity_id, comm_id in partition.items():
        grouped.setdefault(comm_id, []).append(entity_id)
    return grouped


async def _generate_summary(
    community_id: int,
    entity_ids: List[str],
    internal_relations: List[Dict[str, Any]],
    entities: Dict[str, Dict[str, Any]],
) -> str:
    if not settings.openai_api_key or settings.openai_api_key.startswith("sk-test"):
        names = ", ".join(entities.get(eid, {}).get("name", eid) for eid in entity_ids[:10])
        return f"[MODALITÀ TEST] Community {community_id} con entità: {names}."

    max_entities = settings.community_summary_max_entities
    selected_ids = entity_ids[:max_entities]
    selected_entities = [entities[eid] for eid in selected_ids if eid in entities]
    entities_text = "\n".join(
        f"- {e['name']} ({e['type']})" for e in selected_entities
    )
    relations_text = "\n".join(
        f"- {entities.get(r['source_id'], {}).get('name', r['source_id'])} --[{r['type']}]--> {entities.get(r['target_id'], {}).get('name', r['target_id'])}"
        for r in internal_relations[:50]
    )

    prompt = SUMMARY_PROMPT.format(
        entity_count=len(entity_ids),
        entities_text=entities_text or "Nessuna entità",
        relation_count=len(internal_relations),
        relations_text=relations_text or "Nessuna relazione",
    )

    response = await client.chat.completions.create(
        model=settings.community_summary_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=400,
    )
    return response.choices[0].message.content or ""


def _save_community_summary(
    community_id: str,
    summary: str,
    entity_ids: List[str],
    relation_count: int,
    level: str,
):
    with graph_store.driver.session() as session:
        session.run(
            """
            MERGE (cs:CommunitySummary {id: $community_id})
            SET cs.summary = $summary,
                cs.entity_count = $entity_count,
                cs.relation_count = $relation_count,
                cs.level = $level,
                cs.updated_at = datetime()
            WITH cs
            UNWIND $entity_ids AS entity_id
            MATCH (e:Entity {id: entity_id})
            MERGE (e)-[:BELONGS_TO_COMMUNITY]->(cs)
            """,
            community_id=community_id,
            summary=summary,
            entity_count=len(entity_ids),
            relation_count=relation_count,
            level=level,
            entity_ids=entity_ids,
        )


def _clear_all_community_summaries() -> None:
    """Rimuove tutti i nodi CommunitySummary (e i relativi archi) prima di un rebuild.

    La numerazione delle community di Louvain non è stabile tra run successivi (anche a
    parità di grafo): senza questa pulizia, gli archi BELONGS_TO_COMMUNITY di run precedenti
    si accumulerebbero invece di essere sostituiti, e _prune_orphan_summaries non li
    individuerebbe come orfani (hanno ancora entità collegate, solo con id di community
    ormai diversi). Un rebuild completo ad ogni run evita questa deriva.
    """
    with graph_store.driver.session() as session:
        session.run("MATCH (cs:CommunitySummary) DETACH DELETE cs")


async def _process_level(
    level: str,
    community_entities: Dict[int, List[str]],
    entities: Dict[str, Dict[str, Any]],
    relations: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    results = []
    for comm_id, entity_ids in community_entities.items():
        entity_set = set(entity_ids)
        internal_relations = [
            r for r in relations
            if r["source_id"] in entity_set and r["target_id"] in entity_set
        ]
        community_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"community-{level}-{comm_id}"))
        summary = await _generate_summary(comm_id, entity_ids, internal_relations, entities)
        _save_community_summary(
            community_id=community_uuid,
            summary=summary,
            entity_ids=entity_ids,
            relation_count=len(internal_relations),
            level=level,
        )
        results.append({
            "community_id": community_uuid,
            "summary": summary,
            "entity_count": len(entity_ids),
            "relation_count": len(internal_relations),
            "level": level,
        })
        logger.info(
            "[community_detection] Community %s (livello=%s) salvata: %s entità, %s relazioni",
            community_uuid, level, len(entity_ids), len(internal_relations),
        )
    return results


async def run_community_detection(
    algorithm: str = "louvain",
    resolution: float = 1.0,
) -> Dict[str, Any]:
    """Rileva community a due livelli: "leaf" (grana fine, come in precedenza) e "root"
    (massima aggregazione possibile, l'intero grafo in poche community ampie). Il livello
    root permette risposte "globali" coerenti su tutto il KB (vedi community_tool.py),
    invece di dipendere da quali chunk il retrieval vettoriale ha trovato per primi.
    """
    logger.info("[community_detection] Avvio community detection: algorithm=%s resolution=%s", algorithm, resolution)
    G, entities, relations = _build_entity_graph()
    leaf_partition = _detect_communities(G, algorithm, resolution)

    _clear_all_community_summaries()

    if not leaf_partition:
        logger.info("[community_detection] Nessuna community rilevata")
        return {"communities": [], "total_entities": 0, "total_relations": 0}

    root_partition = _detect_root_communities(G, algorithm, resolution) or leaf_partition

    leaf_groups = _group_by_community(leaf_partition)
    results = await _process_level("leaf", leaf_groups, entities, relations)

    if root_partition != leaf_partition:
        root_groups = _group_by_community(root_partition)
        results += await _process_level("root", root_groups, entities, relations)
    else:
        # Grafo troppo piccolo/uniforme per una gerarchia reale: il leaf coincide col root.
        # Rietichettiamo comunque le stesse community come "root" così le query globali le
        # trovano senza dover gestire un caso speciale in community_tool.py.
        results += await _process_level("root", leaf_groups, entities, relations)

    return {
        "communities": results,
        "total_entities": len(entities),
        "total_relations": len(relations),
    }
