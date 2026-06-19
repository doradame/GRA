import asyncio
import uuid

import networkx as nx
import pytest

import app.services.community_detection as cd
from app.services.community_detection import (
    _detect_communities,
    _detect_root_communities,
    _generate_level_summaries,
    _group_by_community,
    _persist_community_summaries,
)


def test_detect_communities_louvain():
    G = nx.Graph()
    G.add_edges_from([
        ("a", "b"), ("a", "c"), ("b", "c"),
        ("d", "e"), ("e", "f"), ("d", "f"),
        ("c", "d"),
    ])
    partitions = _detect_communities(G, "louvain", 1.0)
    assert len(partitions) == 6
    # Entità dello stesso cluster fortemente connesso dovrebbero avere stessa community
    assert partitions["a"] == partitions["b"] == partitions["c"]
    assert partitions["d"] == partitions["e"] == partitions["f"]


def test_detect_communities_empty_graph():
    G = nx.Graph()
    partitions = _detect_communities(G, "louvain", 1.0)
    assert partitions == {}


def test_detect_communities_unsupported_algorithm():
    G = nx.Graph()
    G.add_edge("a", "b")
    with pytest.raises(ValueError):
        _detect_communities(G, "unknown", 1.0)


def test_detect_root_communities_covers_all_nodes_with_at_most_as_many_clusters_as_leaf():
    G = nx.Graph()
    G.add_edges_from([
        ("a", "b"), ("a", "c"), ("b", "c"),
        ("d", "e"), ("e", "f"), ("d", "f"),
        ("c", "d"),
    ])
    leaf = _detect_communities(G, "louvain", 1.0)
    root = _detect_root_communities(G, "louvain", 1.0)

    assert set(root.keys()) == set(G.nodes)
    # Il livello root è per definizione un'aggregazione: non può avere più community del leaf.
    assert len(set(root.values())) <= len(set(leaf.values()))


def test_detect_root_communities_empty_graph():
    G = nx.Graph()
    assert _detect_root_communities(G, "louvain", 1.0) == {}


def test_detect_root_communities_unsupported_algorithm():
    G = nx.Graph()
    G.add_edge("a", "b")
    with pytest.raises(ValueError):
        _detect_root_communities(G, "unknown", 1.0)


def test_group_by_community_groups_entities_by_partition_value():
    partition = {"a": 0, "b": 0, "c": 1}

    grouped = _group_by_community(partition)

    assert grouped == {0: ["a", "b"], 1: ["c"]}


class _FakeSession:
    def __init__(self):
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def run(self, query, **params):
        self.queries.append((query, params))


class _FakeDriver:
    def __init__(self):
        self.session_obj = _FakeSession()

    def session(self):
        return self.session_obj


class _FakeGraphStore:
    """`graph_store` è un singleton GraphStore dove `driver` è una property read-only:
    invece di patchare la property, sostituiamo l'intero riferimento `graph_store` nel
    modulo community_detection."""

    def __init__(self):
        self.driver = _FakeDriver()


def test_generate_level_summaries_builds_deterministic_records():
    # La generazione è solo LLM (qui in demo mode, key vuota) e non tocca Neo4j:
    # è ciò che isola la parte fallibile dal rebuild e lo rende non-distruttivo.
    entities = {
        "e1": {"id": "e1", "name": "Alpha", "type": "C"},
        "e2": {"id": "e2", "name": "Beta", "type": "C"},
    }
    community_entities = {0: ["e1", "e2"]}

    records = asyncio.run(_generate_level_summaries("leaf", community_entities, entities, []))

    assert len(records) == 1
    record = records[0]
    assert record["level"] == "leaf"
    assert record["entity_ids"] == ["e1", "e2"]
    assert record["entity_count"] == 2
    assert record["community_id"] == str(uuid.uuid5(uuid.NAMESPACE_DNS, "community-leaf-0"))


def test_persist_community_summaries_merges_then_deletes_stale(monkeypatch):
    fake_gs = _FakeGraphStore()
    monkeypatch.setattr(cd, "graph_store", fake_gs)
    records = [
        {"community_id": "c1", "summary": "s1", "entity_ids": ["e1"], "entity_count": 1, "relation_count": 0, "level": "leaf"},
        {"community_id": "c2", "summary": "s2", "entity_ids": ["e2"], "entity_count": 1, "relation_count": 0, "level": "root"},
    ]

    _persist_community_summaries(records)

    queries = fake_gs.driver.session_obj.queries
    assert len(queries) == 2
    merge_query, merge_params = queries[0]
    assert "MERGE (cs:CommunitySummary" in merge_query
    assert merge_params["rows"] == records
    delete_query, delete_params = queries[1]
    assert "DETACH DELETE cs" in delete_query
    assert "NOT cs.id IN $new_ids" in delete_query
    assert set(delete_params["new_ids"]) == {"c1", "c2"}


def test_persist_empty_records_only_runs_delete_stale(monkeypatch):
    # Grafo senza community: nessun MERGE, solo il delete-stale con lista vuota
    # (rimuove eventuali summary di run precedenti).
    fake_gs = _FakeGraphStore()
    monkeypatch.setattr(cd, "graph_store", fake_gs)

    _persist_community_summaries([])

    queries = fake_gs.driver.session_obj.queries
    assert len(queries) == 1
    assert "DETACH DELETE cs" in queries[0][0]
    assert queries[0][1]["new_ids"] == []
