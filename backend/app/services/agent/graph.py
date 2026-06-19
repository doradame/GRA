from langgraph.graph import StateGraph, END

from app.services.agent.state import AgentState
from app.services.agent.router import semantic_router
from app.services.agent.nodes import critic_node, direct_answer_node, synthesizer_node
from app.services.agent.tools import run_vector_tool, run_cypher_tool, run_community_tool


def route_by_intent(state: AgentState) -> str:
    return state.get("intent", "factual")


def route_after_critic(state: AgentState) -> str:
    """Se il critic giudica il contesto insufficiente (e il budget di iterazioni non è
    esaurito, vedi critic_node), torna allo stesso tool del round precedente con la query
    riformulata; altrimenti la risposta è pronta."""
    if state.get("critic_verdict") == "insufficient":
        return f"retry_{state.get('intent', 'factual')}"
    return "done"


builder = StateGraph(AgentState)

builder.add_node("semantic_router", semantic_router)
builder.add_node("direct_answer", direct_answer_node)
builder.add_node("vector_tool", run_vector_tool)
builder.add_node("text2cypher_tool", run_cypher_tool)
builder.add_node("community_tool", run_community_tool)
builder.add_node("synthesizer", synthesizer_node)
builder.add_node("critic", critic_node)

builder.set_entry_point("semantic_router")

builder.add_conditional_edges(
    "semantic_router",
    route_by_intent,
    {
        "direct": "direct_answer",
        "factual": "vector_tool",
        "relational": "text2cypher_tool",
        "summary": "community_tool",
    },
)

builder.add_edge("direct_answer", END)
builder.add_edge("vector_tool", "synthesizer")
builder.add_edge("text2cypher_tool", "synthesizer")
builder.add_edge("community_tool", "synthesizer")
builder.add_edge("synthesizer", "critic")

builder.add_conditional_edges(
    "critic",
    route_after_critic,
    {
        "retry_factual": "vector_tool",
        "retry_relational": "text2cypher_tool",
        "retry_summary": "community_tool",
        "done": END,
    },
)

agent_graph = builder.compile()
