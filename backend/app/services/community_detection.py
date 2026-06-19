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
        max_completion_tokens=400,
    )
    return response.choices[0].message.content or ""


def _persist_community_summaries(records: List[Dict[str, Any]]) -> None:
    """Scrive i CommunitySummary su Neo4j in modo idempotente e non-distruttivo.

    1) MERGE batched (id UUID5 deterministici `community-{level}-{comm_id}`): un re-run
       sullo stesso grafo aggiorna in-place i nodi esistenti invece di duplicarli, perché
       Louvain (random_state=42) assegna gli stessi comm_id a parità di grafo → stessi id.
    2) Delete-stale DOPO: rimuove i CommunitySummary di run precedenti i cui id non sono
       più tra quelli appena scritti (es. entità cancellate o grafo mutato → comm_id
       diversi). Sostituisce il vecchio `_clear_all_community_summaries()` (che cancellava
       TUTTO prima di rigenerare), ed è eseguito per ultimo: un crash a metà del MERGE
       lascia vecchi + nuovi parziali (duplicati, non perdita di dati); al retry il MERGE
       completa e il delete pulisce i superflui.
    """
    new_ids = [r["community_id"] for r in records]
    with graph_store.driver.session() as session:
        if records:
            session.run(
                """
                UNWIND $rows AS row
                MERGE (cs:CommunitySummary {id: row.community_id})
                SET cs.summary = row.summary,
                    cs.entity_count = row.entity_count,
                    cs.relation_count = row.relation_count,
                    cs.level = row.level,
                    cs.updated_at = datetime()
                WITH cs, row
                UNWIND row.entity_ids AS entity_id
                MATCH (e:Entity {id: entity_id})
                MERGE (e)-[:BELONGS_TO_COMMUNITY]->(cs)
                """,
                rows=records,
            )
        # Rimuovi i summary di run precedenti non più validi (id non presenti nel run corrente).
        session.run(
            """
            MATCH (cs:CommunitySummary)
            WHERE NOT cs.id IN $new_ids
            DETACH DELETE cs
            """,
            new_ids=new_ids,
        )


async def _generate_level_summaries(
    level: str,
    community_entities: Dict[int, List[str]],
    entities: Dict[str, Dict[str, Any]],
    relations: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Genera i summary delle community di un livello SOLO in memoria (chiamate LLM).

    Nessuna scrittura su Neo4j: ritorna record pronti per `_persist_community_summaries`.
    Isolare la generazione (la parte costosa e fallibile) dalla scrittura è ciò che rende
    il rebuild non-distruttivo: un crash qui lascia i CommunitySummary esistenti intatti.
    """
    records: List[Dict[str, Any]] = []
    for comm_id, entity_ids in community_entities.items():
        entity_set = set(entity_ids)
        internal_relations = [
            r for r in relations
            if r["source_id"] in entity_set and r["target_id"] in entity_set
        ]
        community_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"community-{level}-{comm_id}"))
        summary = await _generate_summary(comm_id, entity_ids, internal_relations, entities)
        records.append({
            "community_id": community_uuid,
            "summary": summary,
            "entity_ids": entity_ids,
            "entity_count": len(entity_ids),
            "relation_count": len(internal_relations),
            "level": level,
        })
        logger.info(
            "[community_detection] Community %s (livello=%s) generata: %s entità, %s relazioni",
            community_uuid, level, len(entity_ids), len(internal_relations),
        )
    return records


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

    if not leaf_partition:
        logger.info("[community_detection] Nessuna community rilevata")
        # Grafo senza community: persistenzia l'insieme vuoto (delete-stale rimuove i
        # summary di run precedenti) per mantenere il grafo coerente con quello attuale.
        _persist_community_summaries([])
        return {"communities": [], "total_entities": len(entities), "total_relations": len(relations)}

    root_partition = _detect_root_communities(G, algorithm, resolution) or leaf_partition

    # Genera TUTTI i summary in memoria prima di qualsiasi scrittura Neo4j: se il job
    # crasha qui (OOM, rate-limit LLM) i CommunitySummary esistenti restano intatti. La
    # persistenza successiva è idempotenta + delete-stale, quindi il rebuild è
    # non-distruttivo anche se interrotto e ripreso.
    leaf_groups = _group_by_community(leaf_partition)
    records = await _generate_level_summaries("leaf", leaf_groups, entities, relations)

    if root_partition != leaf_partition:
        root_groups = _group_by_community(root_partition)
        records += await _generate_level_summaries("root", root_groups, entities, relations)
    else:
        # Grafo troppo piccolo/uniforme per una gerarchia reale: il leaf coincide col root.
        # Rietichettiamo comunque le stesse community come "root" così le query globali le
        # trovano senza dover gestire un caso speciale in community_tool.py.
        records += await _generate_level_summaries("root", leaf_groups, entities, relations)

    _persist_community_summaries(records)

    return {
        "communities": records,
        "total_entities": len(entities),
        "total_relations": len(relations),
    }
