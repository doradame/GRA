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


CRITIC_PROMPT = """Sei un revisore critico per un assistente Graph RAG. Decidi se la RISPOSTA BOZZA,
basata sul CONTESTO raccolto, risponde in modo completo e fondato alla DOMANDA dell'utente, oppure
se serve un altro giro di ricerca nella knowledge base.

Segnala insufficiente (sufficient=false) se:
- la risposta bozza dichiara esplicitamente di non avere informazioni sufficienti;
- il contesto è vuoto o chiaramente non pertinente alla domanda;
- la domanda ha più parti e il contesto ne copre solo alcune.

Se insufficiente, proponi in refined_query UNA query di ricerca alternativa (più specifica, scomposta
in una sotto-domanda, o con sinonimi/termini diversi) da usare per il prossimo giro di retrieval.
NON scrivere mai la risposta finale in refined_query, solo una query di ricerca.

Rispondi SOLO con JSON:
{"sufficient": true|false, "reasoning": "breve spiegazione", "refined_query": "..."}
"""


async def critic_node(state: AgentState) -> AgentState:
    """Valuta se il contesto/risposta raccolti finora bastano, o se serve un altro giro di
    retrieval con una query riformulata (loop di auto-correzione su intent factual/relational/
    summary; "direct" non passa di qui, va dritto a END).

    Il numero massimo di giri è settings.agent_max_iterations: evita loop infiniti e contiene
    il costo extra in chiamate LLM per domanda (1 chiamata critic + 1 giro di retrieval/sintesi
    in più per ogni retry).
    """
    iteration = state.get("iteration", 0)
    max_iterations = max(1, settings.agent_max_iterations)

    if iteration + 1 >= max_iterations:
        logger.info(
            "[critic] Budget di iterazioni esaurito (%s/%s), rispondo con quanto raccolto",
            iteration + 1,
            max_iterations,
        )
        return {
            **state,
            "critic_verdict": "sufficient",
            "critic_reasoning": "budget iterazioni esaurito",
            "iteration": iteration + 1,
        }

    if not settings.openai_api_key or settings.openai_api_key.startswith("sk-test"):
        return {
            **state,
            "critic_verdict": "sufficient",
            "critic_reasoning": "modalità test",
            "iteration": iteration + 1,
        }

    query = state.get("user_query", "")
    context = state.get("context", "")
    answer = state.get("answer", "")

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": CRITIC_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Domanda: {query}\n\n"
                        # Niente troncamento aggressivo: il critic deve giudicare la bozza/contesto
                        # reali, non una versione tagliata a metà frase (con modelli più verbosi e
                        # contesti ricchi, un taglio piccolo produce falsi "tronca"/"fonte non nel
                        # contesto" perché il critic vede solo l'inizio). Il cap resta solo come
                        # argine a input patologicamente lunghi.
                        f"Contesto raccolto:\n{context[:40000] or '(vuoto)'}\n\n"
                        f"Risposta bozza:\n{answer[:12000] or '(vuota)'}"
                    ),
                },
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(response.choices[0].message.content or "{}")
        sufficient = bool(parsed.get("sufficient", True))
        reasoning = parsed.get("reasoning", "")
        refined_query = (parsed.get("refined_query") or "").strip() or query
    except Exception as exc:
        logger.warning("[critic] Errore valutazione critica, procedo come sufficiente: %s", exc)
        sufficient, reasoning, refined_query = True, f"errore critic: {exc}", query

    logger.info("[critic] iterazione=%s sufficient=%s reasoning=%s", iteration + 1, sufficient, reasoning)

    next_state = {
        **state,
        "critic_verdict": "sufficient" if sufficient else "insufficient",
        "critic_reasoning": reasoning,
        "iteration": iteration + 1,
    }
    if not sufficient:
        # Sovrascrive user_query con la query riformulata per il prossimo giro: i tool node
        # (vector_tool/cypher_tool/community_tool) e il prossimo critic_node la leggono da qui.
        # Il logging della domanda originale (rag_engine.chat_completion) non è affetto perché
        # usa una variabile locale catturata prima di invocare il grafo, non lo stato finale.
        next_state["user_query"] = refined_query
    return next_state


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
