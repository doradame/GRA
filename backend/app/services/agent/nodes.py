import json
import logging
import time
import uuid
from typing import List, Dict, Any

from openai import AsyncOpenAI

from app.core.config import get_settings
from app.services.agent.state import AgentState, Citation

settings = get_settings()
client = AsyncOpenAI(api_key=settings.openai_api_key)
logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """Sei un assistente conversazionale che aiuta l'utente usando i documenti caricati nella knowledge base.

Regole:
- Per domande sui documenti, usa SOLO le informazioni presenti nel contesto fornito.
- Se la risposta si trova nei documenti, rispondi in modo completo, chiaro e naturale; non limitarti a una frase secca.
- Quando citi una fonte, usa riferimenti leggibili: file, pagina se disponibile, sezione/parte se disponibile.
- Non citare mai ID tecnici di chunk o UUID nella risposta all'utente.
- Quando utile, includi un breve virgolettato dal contesto.
- Se l'utente fa un saluto o una domanda generale (es. "chi sei?", "ciao"), rispondi normalmente in modo cordiale.
- Se l'utente chiede qualcosa non presente nei documenti, spiega gentilmente che non hai informazioni al riguardo nella knowledge base.
"""


def _build_context_from_state(state: AgentState) -> str:
    parts = []
    if state.get("vector_results"):
        parts.append(state["vector_results"].context)
    if state.get("cypher_results"):
        parts.append(f"\n\nRisultati dalla query sul grafo:\n{state['cypher_results'].summary}")
    if state.get("community_results"):
        parts.append(state["community_results"].context)
    return "\n".join(parts).strip()


def _collect_citations(state: AgentState) -> List[Citation]:
    citations: List[Citation] = []
    if state.get("vector_results"):
        citations.extend(state["vector_results"].citations)
    return citations


async def direct_answer(state: AgentState) -> AgentState:
    query = state.get("user_query", "")
    if not settings.openai_api_key or settings.openai_api_key.startswith("sk-test"):
        answer = "Ciao! Sono l'assistente Graph RAG. Configura una chiave OpenAI valida per ricevere risposte generate dal modello."
        return {**state, "answer": answer}

    messages = [
        {"role": "system", "content": "Sei un assistente cordiale e conciso."},
        {"role": "user", "content": query},
    ]
    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=messages,
        temperature=settings.llm_temperature,
    )
    answer = response.choices[0].message.content or ""
    return {**state, "answer": answer}


async def synthesizer(state: AgentState) -> AgentState:
    context = _build_context_from_state(state)
    citations = _collect_citations(state)
    messages = state.get("messages", [])
    query = state.get("user_query", "")

    if not settings.openai_api_key or settings.openai_api_key.startswith("sk-test"):
        answer = (
            "[MODALITÀ TEST] Ho raccolto il contesto dagli strumenti. "
            "Configura una chiave OpenAI valida per ricevere risposte generate dal modello."
        )
        return {**state, "answer": answer, "context": context, "citations": citations}

    system_content = SYSTEM_PROMPT
    if context.strip():
        system_content += "\n\nCONTESTO:\n" + context
    else:
        system_content += "\n\nNon sono stati trovati documenti rilevanti per questa domanda."

    augmented_messages = [{"role": "system", "content": system_content}] + messages

    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=augmented_messages,
        temperature=settings.llm_temperature,
    )
    answer = response.choices[0].message.content or ""
    return {**state, "answer": answer, "context": context, "citations": citations}


def build_chat_response(state: AgentState) -> Dict[str, Any]:
    citations = [c.model_dump() for c in state.get("citations", [])]
    return {
        "id": str(uuid.uuid4()),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": settings.openai_model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": state.get("answer", "")},
                "finish_reason": "stop",
            }
        ],
        "citations": citations,
    }


async def direct_answer_node(state: AgentState) -> AgentState:
    return await direct_answer(state)


async def synthesizer_node(state: AgentState) -> AgentState:
    return await synthesizer(state)
