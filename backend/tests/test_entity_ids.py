from app.services.entity_ids import canonical_entity_id


def test_canonical_entity_id_is_deterministic():
    assert canonical_entity_id("ACME Corp", "Organization") == canonical_entity_id("ACME Corp", "Organization")


def test_canonical_entity_id_is_case_and_whitespace_insensitive():
    assert canonical_entity_id("  ACME   corp  ", "Organization") == canonical_entity_id("acme corp", "organization")


def test_canonical_entity_id_type_separates_homonyms():
    # Stesso nome, tipo diverso -> id diverso (Milano luogo vs organizzazione).
    assert canonical_entity_id("Milano", "Luogo") != canonical_entity_id("Milano", "Organizzazione")


def test_canonical_entity_id_is_32_chars():
    assert len(canonical_entity_id("x", "y")) == 32
