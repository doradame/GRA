from app.services.agent.graph import route_after_critic, route_by_intent


def test_route_by_intent_defaults_to_factual():
    assert route_by_intent({}) == "factual"
    assert route_by_intent({"intent": "relational"}) == "relational"


def test_route_after_critic_done_when_sufficient():
    assert route_after_critic({"critic_verdict": "sufficient", "intent": "factual"}) == "done"


def test_route_after_critic_retries_same_tool_as_original_intent():
    assert route_after_critic({"critic_verdict": "insufficient", "intent": "factual"}) == "retry_factual"
    assert route_after_critic({"critic_verdict": "insufficient", "intent": "relational"}) == "retry_relational"
    assert route_after_critic({"critic_verdict": "insufficient", "intent": "summary"}) == "retry_summary"
