import json
import logging
from typing import Literal

from openai import AsyncOpenAI

from app.core.config import get_settings
from app.services.agent.state import AgentState

settings = get_settings()
client = AsyncOpenAI(api_key=settings.openai_api_key)
logger = logging.getLogger(__name__)

Intent = Literal["factual", "relational", "summary", "direct"]


ROUTER_PROMPT = """Sei un router semantico per un assistente Graph RAG. Classifica l'intento dell'ultima domanda utente in una di queste categorie:

- factual: domanda il cui contenuto è probabilmente in uno o più chunk di documento (es. "Cosa dice il documento X riguardo Y?", "Quali requisiti sono previsti?"). Include anche domande su un singolo attributo di una singola entità (es. "Chi è il responsabile di X?", "Chi ha scritto Y?", "Quando è stato pubblicato Z?") quando la risposta è probabilmente contenuta in un singolo passaggio di testo, non richiede di attraversare relazioni tra più entità diverse.
- relational: domande sulle connessioni/dipendenze TRA PIÙ entità distinte (es. "Quali sistemi dipendono dal Firewall X?", "Chi è collegato a Y?", "Quali prodotti sono esclusi da Z?").
- summary: domande di sintesi o panoramica (es. "Quali sono le tematiche principali?", "Riassumi gli argomenti trattati").
- direct: saluti, domande sull'assistente, domande generiche senza riferimento ai documenti (es. "ciao", "chi sei?", "come funzioni?").

Rispondi SOLO con un JSON nel formato:
{"intent": "factual|relational|summary|direct", "reasoning": "breve spiegazione"}

Esempi:
Utente: "Ciao"
{"intent": "direct", "reasoning": "saluto"}

Utente: "Quali requisiti sono previsti per l'accesso ai dati?"
{"intent": "factual", "reasoning": "domanda fattuale su contenuto documentale"}

Utente: "Quali sistemi dipendono dal Firewall DMZ?"
{"intent": "relational", "reasoning": "domanda su relazioni tra entità"}

Utente: "Chi è il responsabile tecnico del progetto Aurora-7?"
{"intent": "factual", "reasoning": "attributo di una singola entità, risposta probabile in un singolo passaggio"}

Utente: "Quali sono le tematiche principali del documento?"
{"intent": "summary", "reasoning": "domanda di sintesi"}
"""


_RELATIONAL_KEYWORDS = [
    "quali", "elenca", "dipende", "dipendono", "collegato", "collegati", "collegata",
    "relazione", "relazioni", "connessione", "connessioni", "collega", "legati", "legato",
    "collegamento", "collegamenti", "associato", "associati", "collegato a", "legato a",
]

_SUMMARY_KEYWORDS = [
    "sommario", "temi principali", "riassumi", "panoramica", "argomenti", "tema",
    "argomento", "trattati", "trattate", "sintesi", "overview", "riassunto",
]

_DIRECT_KEYWORDS = [
    "ciao", "salve", "buongiorno", "buonasera", "chi sei", "come stai",
    "cosa sai fare", "come funzioni", "chi ti ha creato",
]


def _heuristic_intent(query: str) -> tuple[Intent, str]:
    lowered = query.lower()
    for kw in _DIRECT_KEYWORDS:
        if kw in lowered:
            return "direct", f"fallback euristico: keyword '{kw}'"
    for kw in _SUMMARY_KEYWORDS:
        if kw in lowered:
            return "summary", f"fallback euristico: keyword '{kw}'"
    for kw in _RELATIONAL_KEYWORDS:
        if kw in lowered:
            return "relational", f"fallback euristico: keyword '{kw}'"
    return "factual", "fallback euristico: nessuna keyword specifica"


async def semantic_router(state: AgentState) -> AgentState:
    query = state.get("user_query", "").strip()
    if not query:
        return {**state, "intent": "direct", "reasoning": "query vuota"}

    if not settings.openai_api_key or settings.openai_api_key.startswith("sk-test"):
        intent, reasoning = _heuristic_intent(query)
        logger.info("[router] Modalità test / senza chiave OpenAI: intent=%s", intent)
        return {**state, "intent": intent, "reasoning": reasoning}

    try:
        messages = [
            {"role": "system", "content": ROUTER_PROMPT},
            {"role": "user", "content": f"Utente: {query}"},
        ]
        response = await client.chat.completions.create(
            model=settings.router_model,
            messages=messages,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        parsed = json.loads(content)
        intent = parsed.get("intent", "factual")
        reasoning = parsed.get("reasoning", "")
        if intent not in {"factual", "relational", "summary", "direct"}:
            intent, reasoning = _heuristic_intent(query)
        logger.info("[router] LLM intent=%s reasoning=%s", intent, reasoning)
        return {**state, "intent": intent, "reasoning": reasoning}
    except Exception as exc:
        logger.warning("[router] Errore LLM, uso fallback euristico: %s", exc)
        intent, reasoning = _heuristic_intent(query)
        return {**state, "intent": intent, "reasoning": reasoning}
