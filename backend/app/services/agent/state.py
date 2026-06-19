from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, TypedDict
from pydantic import BaseModel


class Citation(BaseModel):
    chunk_id: str
    document_id: str
    filename: str
    text: str
    score: float
    chunk_index: Optional[int] = None
    section_title: Optional[str] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    document_page_count: Optional[int] = None
    quote: Optional[str] = None
    reference: Optional[str] = None


class VectorToolResult(BaseModel):
    chunks: List[dict]
    local_graph_facts: List[str]
    context: str
    citations: List[Citation]


class CypherToolResult(BaseModel):
    cypher: str
    results: List[dict]
    summary: str
    error: Optional[str] = None


class CommunitySummary(BaseModel):
    community_id: str
    summary: str
    entity_count: int
    relation_count: int
    updated_at: datetime


class CommunityToolResult(BaseModel):
    summaries: List[str]
    community_ids: List[str]
    context: str


class AgentState(TypedDict, total=False):
    # Input
    messages: List[Dict[str, str]]
    user_query: str
    user_id: Optional[str]

    # Router decision
    intent: Literal["factual", "relational", "summary", "direct"]
    reasoning: str

    # Tool results
    vector_results: Optional[VectorToolResult]
    cypher_results: Optional[CypherToolResult]
    community_results: Optional[CommunityToolResult]

    # Final context and answer
    context: str
    citations: List[Citation]
    answer: Optional[str]
    error: Optional[str]

    # Loop di auto-correzione (critic): conta i giri di retrieval già fatti, l'ultimo verdetto
    # e l'eventuale query riformulata da usare nel prossimo giro (vedi agent/nodes.py::critic_node).
    iteration: int
    critic_verdict: Literal["sufficient", "insufficient"]
    critic_reasoning: str
