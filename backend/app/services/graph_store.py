from typing import List, Dict, Any
import logging
import re
import hashlib
import time
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

DEFAULT_RELATION_TYPE = "RELATED_TO"


def _normalize_entity_key(name: str, entity_type: str) -> str:
    normalized_name = " ".join(name.casefold().strip().split())
    normalized_type = " ".join(entity_type.casefold().strip().split()) or "unknown"
    digest = hashlib.sha256(f"{normalized_type}:{normalized_name}".encode("utf-8")).hexdigest()
    return digest[:32]


def _sanitize_relation_type(value: str) -> str:
    rel_type = re.sub(r"[^A-Za-z0-9_]", "_", value.upper().strip())
    rel_type = re.sub(r"_+", "_", rel_type).strip("_")
    if not rel_type or not rel_type[0].isalpha():
        return DEFAULT_RELATION_TYPE
    return rel_type


class GraphStore:
    def __init__(self):
        self._driver = None

    @property
    def driver(self):
        if self._driver is None:
            logger.info("[graph] Initializing Neo4j driver: %s", settings.neo4j_uri)
            self._driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password),
            )
            self._wait_for_neo4j()
            self._init_schema()
            logger.info("[graph] Neo4j driver ready")
        return self._driver

    def _wait_for_neo4j(self, max_retries: int = 30, delay: float = 1.0):
        logger.info("[graph] Waiting for Neo4j to be available...")
        for attempt in range(max_retries):
            try:
                with self._driver.session() as session:
                    session.run("RETURN 1")
                logger.info("[graph] Neo4j available after %s attempts", attempt + 1)
                return
            except ServiceUnavailable:
                logger.debug("[graph] Neo4j not ready yet, attempt %s/%s", attempt + 1, max_retries)
                if attempt == max_retries - 1:
                    logger.error("[graph] Neo4j did not become available after %s attempts", max_retries)
                    raise
                time.sleep(delay)

    def _init_schema(self):
        logger.info("[graph] Initializing Neo4j constraints")
        with self._driver.session() as session:
            session.run("CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE")
            session.run("CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (c:Chunk) REQUIRE c.id IS UNIQUE")
            session.run("CREATE CONSTRAINT document_id IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE")
            session.run("CREATE CONSTRAINT community_summary_id IF NOT EXISTS FOR (cs:CommunitySummary) REQUIRE cs.id IS UNIQUE")
        logger.info("[graph] Neo4j constraints initialized")

    def close(self):
        if self._driver is not None:
            logger.info("[graph] Closing Neo4j driver")
            self._driver.close()

    def add_document(self, doc_id: str, filename: str, content_type: str, user_id: str | None = None):
        logger.debug("[graph] Adding document node: %s", doc_id)
        with self.driver.session() as session:
            session.run(
                """
                MERGE (d:Document {id: $doc_id})
                SET d.filename = $filename, d.content_type = $content_type, d.user_id = $user_id
                """,
                doc_id=doc_id,
                filename=filename,
                content_type=content_type,
                user_id=user_id,
            )
        logger.debug("[graph] Document node added: %s", doc_id)

    def add_chunk(self, chunk_id: str, doc_id: str, text: str, index: int, user_id: str | None = None):
        with self.driver.session() as session:
            session.run(
                """
                MERGE (c:Chunk {id: $chunk_id})
                SET c.text = $text, c.index = $index, c.user_id = $user_id
                WITH c
                MATCH (d:Document {id: $doc_id})
                MERGE (c)-[:BELONGS_TO]->(d)
                """,
                chunk_id=chunk_id,
                doc_id=doc_id,
                text=text,
                index=index,
                user_id=user_id,
            )

    def add_entities_and_relations(
        self,
        chunk_id: str,
        entities: List[Dict[str, Any]],
        relations: List[Dict[str, Any]],
    ):
        with self.driver.session() as session:
            for entity in entities:
                name = str(entity.get("name", "")).strip()
                entity_type = str(entity.get("type", "Unknown")).strip() or "Unknown"
                if not name:
                    continue
                entity_id = str(entity.get("id") or _normalize_entity_key(name, entity_type))
                session.run(
                    """
                    MERGE (e:Entity {id: $id})
                    SET e.name = $name, e.type = $type, e.normalized_name = $normalized_name
                    WITH e
                    MATCH (c:Chunk {id: $chunk_id})
                    MERGE (c)-[:MENTIONS]->(e)
                    """,
                    id=entity_id,
                    name=name,
                    type=entity_type,
                    normalized_name=" ".join(name.casefold().strip().split()),
                    chunk_id=chunk_id,
                )
            for rel in relations:
                rel_type = _sanitize_relation_type(str(rel.get("type", DEFAULT_RELATION_TYPE)))
                session.run(
                    f"""
                    MATCH (s:Entity {{id: $source_id}})
                    MATCH (t:Entity {{id: $target_id}})
                    MERGE (s)-[r:{rel_type}]->(t)
                    SET r += $props
                    """,
                    source_id=rel.get("source_id"),
                    target_id=rel.get("target_id"),
                    props=rel.get("properties", {}),
                )

    @staticmethod
    def _stringify_name(value: Any) -> str:
        """Normalizza il nome di un nodo in stringa singola.

        APOC mergeNodes può combinare proprietà `name` in array; in tal caso
        prendiamo il primo elemento e ignoriamo i duplicati successivi.
        """
        if isinstance(value, list):
            value = value[0] if value else ""
        return str(value) if value is not None else ""

    @classmethod
    def _clean_name(cls, value: Any) -> str:
        """Stringify and collapse whitespace/newlines left over from PDF text extraction."""
        return " ".join(cls._stringify_name(value).split())

    def explore_entity(self, entity_name: str, depth: int = 1, limit: int = 25) -> Dict[str, Any]:
        logger.debug("[graph] Exploring entity: %s (depth=%s)", entity_name, depth)
        # Match entities by name first (independent of whether they have any relation), then
        # separately expand to other Entity nodes within `depth` hops. This keeps results for
        # entities that only have MENTIONS edges to text chunks (no LLM-extracted relations),
        # and avoids surfacing raw chunk/document nodes as fake "entities" in the response.
        query = f"""
        MATCH (e:Entity)
        WHERE toLower(CASE WHEN apoc.meta.cypher.type(e.name) STARTS WITH 'LIST' THEN e.name[0] ELSE e.name END) CONTAINS toLower($entity_name)
        WITH e
        LIMIT $limit
        OPTIONAL MATCH path = (e)-[*1..{depth}]-(connected:Entity)
        WHERE connected <> e
        RETURN e, connected, relationships(path) AS rels
        LIMIT 200
        """
        with self.driver.session() as session:
            result = session.run(query, entity_name=entity_name, limit=limit)
            entities = {}
            relations = []
            seen_relations = set()
            for record in result:
                e = record["e"]
                entities[e.element_id] = {"id": e["id"], "name": self._clean_name(e["name"]), "type": e["type"]}
                conn = record["connected"]
                if conn is None:
                    continue
                entities[conn.element_id] = {
                    "id": conn.get("id"),
                    "name": self._clean_name(conn.get("name", "")),
                    "type": conn.get("type", "Unknown"),
                }
                for rel in record["rels"] or []:
                    rel_key = (rel.start_node.element_id, rel.end_node.element_id, rel.type)
                    if rel_key in seen_relations:
                        continue
                    seen_relations.add(rel_key)
                    relations.append({
                        "source": self._clean_name(rel.start_node.get("name", "")),
                        "target": self._clean_name(rel.end_node.get("name", "")),
                        "type": rel.type,
                    })
            logger.debug("[graph] Explore returned %s entities and %s relations", len(entities), len(relations))
            return {"entities": list(entities.values()), "relations": relations}

    def delete_document(self, doc_id: str):
        logger.info("[graph] Deleting document graph data: %s", doc_id)
        with self.driver.session() as session:
            session.run(
                """
                MATCH (d:Document {id: $doc_id})
                OPTIONAL MATCH (d)<-[:BELONGS_TO]-(c:Chunk)
                OPTIONAL MATCH (c)-[r]-()
                DELETE r, c, d
                """,
                doc_id=doc_id,
            )
            # Remove entities that are no longer mentioned by any chunk
            session.run(
                """
                MATCH (e:Entity)
                WHERE NOT (:Chunk)-[:MENTIONS]->(e)
                DETACH DELETE e
                """
            )
        logger.info("[graph] Deleted document graph data: %s", doc_id)

    def reset(self):
        logger.warning("[graph] Resetting entire graph")
        with self.driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
        logger.warning("[graph] Graph reset complete")

    def get_stats(self, user_id: str | None = None) -> Dict[str, int]:
        logger.debug("[graph] Collecting graph stats")
        with self.driver.session() as session:
            if user_id:
                doc_count = session.run(
                    "MATCH (d:Document {user_id: $user_id}) RETURN count(d) AS c",
                    user_id=user_id,
                ).single()["c"]
                chunk_count = session.run(
                    "MATCH (c:Chunk {user_id: $user_id}) RETURN count(c) AS c",
                    user_id=user_id,
                ).single()["c"]
                rel_types = session.run(
                    "CALL db.relationshipTypes() YIELD relationshipType RETURN collect(relationshipType) AS types"
                ).single()["types"]
                if "MENTIONS" in rel_types:
                    entity_count = session.run(
                        """
                        MATCH (c:Chunk {user_id: $user_id})
                        OPTIONAL MATCH (c)-[:MENTIONS]->(e:Entity)
                        RETURN count(DISTINCT e) AS c
                        """,
                        user_id=user_id,
                    ).single()["c"]
                    rel_count = session.run(
                        """
                        MATCH (c:Chunk {user_id: $user_id})
                        OPTIONAL MATCH (c)-[:MENTIONS]->(s:Entity)-[r]->(t:Entity)
                        RETURN count(DISTINCT r) AS c
                        """,
                        user_id=user_id,
                    ).single()["c"]
                else:
                    entity_count = 0
                    rel_count = 0
            else:
                doc_count = session.run("MATCH (d:Document) RETURN count(d) AS c").single()["c"]
                chunk_count = session.run("MATCH (c:Chunk) RETURN count(c) AS c").single()["c"]
                entity_count = session.run("MATCH (e:Entity) RETURN count(e) AS c").single()["c"]
                rel_count = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
            logger.debug(
                "[graph] Stats: documents=%s chunks=%s entities=%s relations=%s",
                doc_count,
                chunk_count,
                entity_count,
                rel_count,
            )
            return {
                "documents": doc_count,
                "chunks": chunk_count,
                "entities": entity_count,
                "relations": rel_count,
            }

    def explore_local_subgraph(self, chunk_ids: List[str], limit: int = 200) -> List[Dict[str, str]]:
        logger.debug("[graph] Exploring local subgraph for %s chunks", len(chunk_ids))
        if not chunk_ids:
            return []
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (c:Chunk)-[:MENTIONS]->(e:Entity)-[r]-(e2:Entity)
                WHERE c.id IN $chunk_ids
                RETURN e.name AS source, type(r) AS rel_type, e2.name AS target
                LIMIT $limit
                """,
                chunk_ids=chunk_ids,
                limit=limit,
            )
            return [
                {
                    "source": self._stringify_name(record.get("source")),
                    "target": self._stringify_name(record.get("target")),
                    "type": record.get("rel_type", "RELATED_TO"),
                }
                for record in result
            ]

    def get_community_summaries(self, entity_ids: List[str], limit: int = 20) -> List[Dict[str, Any]]:
        if not entity_ids:
            return []
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (e:Entity)-[:BELONGS_TO_COMMUNITY]->(cs:CommunitySummary)
                WHERE e.id IN $entity_ids
                RETURN cs.id AS community_id,
                       cs.summary AS summary,
                       cs.entity_count AS entity_count,
                       cs.relation_count AS relation_count,
                       cs.updated_at AS updated_at
                ORDER BY cs.entity_count DESC
                LIMIT $limit
                """,
                entity_ids=entity_ids,
                limit=limit,
            )
            summaries = []
            seen = set()
            for record in result:
                cid = record["community_id"]
                if cid in seen:
                    continue
                seen.add(cid)
                summaries.append(record.data())
            return summaries

    def add_community_summary(
        self,
        community_id: str,
        summary: str,
        entity_ids: List[str],
        relation_count: int,
    ):
        with self.driver.session() as session:
            session.run(
                """
                MERGE (cs:CommunitySummary {id: $community_id})
                SET cs.summary = $summary,
                    cs.entity_count = $entity_count,
                    cs.relation_count = $relation_count,
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
                entity_ids=entity_ids,
            )


graph_store = GraphStore()
