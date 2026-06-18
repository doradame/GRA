import pytest

from app.services.agent.tools.cypher_tool import validate_cypher


def test_validate_valid_read_query():
    cypher = """
    MATCH (fw:Entity)-[:DIPENDE_DA|BLOCCATO_DA]-(sys:Entity)
    WHERE toLower(fw.name) CONTAINS toLower($term)
    RETURN sys.name AS sistema
    LIMIT 20
    """
    assert validate_cypher(cypher) is True


def test_validate_rejects_write_query():
    cypher = "MATCH (n) DELETE n"
    assert validate_cypher(cypher) is False


def test_validate_rejects_merge():
    cypher = "MERGE (n:Entity {name: 'test'}) RETURN n"
    assert validate_cypher(cypher) is False


def test_validate_rejects_non_match_start():
    cypher = "RETURN 1"
    assert validate_cypher(cypher) is False


def test_validate_empty_query():
    assert validate_cypher("") is False
