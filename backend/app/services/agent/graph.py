from langgraph.graph import StateGraph, END

from app.services.agent.state import AgentState
from app.services.agent.router import semantic_router
from app.services.agent.nodes import direct_answer_node, synthesizer_node
from app.services.agent.tools import run_vector_tool, run_cypher_tool, run_community_tool


def route_by_intent(state: AgentState) -> str:
    return state.get("intent", "factual")


builder = StateGraph(AgentState)

builder.add_node("semantic_router", semantic_router)
builder.add_node("direct_answer", direct_answer_node)
builder.add_node("vector_tool", run_vector_tool)
builder.add_node("text2cypher_tool", run_cypher_tool)
builder.add_node("community_tool", run_community_tool)
builder.add_node("synthesizer", synthesizer_node)

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
builder.add_edge("synthesizer", END)

agent_graph = builder.compile()
