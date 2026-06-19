import pytest

from app.services.api_usage import estimate_cost_usd


def test_estimate_cost_gpt4o_mini():
    cost = estimate_cost_usd("gpt-4o-mini", 1_000_000, 500_000)
    assert cost == pytest.approx(0.45, 0.01)


def test_estimate_cost_embedding():
    cost = estimate_cost_usd("text-embedding-3-large", 1_000_000, 0)
    assert cost == pytest.approx(0.13, 0.01)


def test_estimate_cost_unknown_model_fallback():
    cost = estimate_cost_usd("unknown-model", 1_000_000, 500_000)
    assert cost == pytest.approx(0.45, 0.01)
