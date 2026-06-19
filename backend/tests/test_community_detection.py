import networkx as nx
import pytest

from app.services.community_detection import (
    _detect_communities,
    _detect_root_communities,
    _group_by_community,
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
