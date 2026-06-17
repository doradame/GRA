from app.core.config import get_settings
from app.services.embeddings import _fallback_embedding


def test_fallback_embedding_uses_configured_vector_size():
    vector = _fallback_embedding("hello")

    assert len(vector) == get_settings().embedding_dimensions
