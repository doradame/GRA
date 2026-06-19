import asyncio
import logging
from typing import List

from openai import AsyncOpenAI

from app.core.config import get_settings
from app.services.api_usage import increment_contextual_retrieval_calls

settings = get_settings()
client = AsyncOpenAI(api_key=settings.openai_api_key)
logger = logging.getLogger(__name__)


CONTEXT_PROMPT = """Questo è il documento completo (eventualmente troncato) a cui appartiene il chunk seguente:

<documento>
{document}
</documento>

Ecco il chunk da situare nel documento:

<chunk>
{chunk}
</chunk>

Scrivi un breve contesto (massimo 2 frasi, in italiano) che situi questo chunk all'interno del documento completo, utile a migliorarne il recupero in un sistema di ricerca semantica. Risolvi eventuali riferimenti impliciti (pronomi, "il sistema precedente", sigle già definite altrove nel documento, ecc.). Rispondi SOLO con il contesto, senza preamboli."""


async def _generate_one_context(document: str, chunk: str, semaphore: asyncio.Semaphore) -> str:
    async with semaphore:
        try:
            response = await client.chat.completions.create(
                model=settings.contextual_retrieval_model,
                messages=[{"role": "user", "content": CONTEXT_PROMPT.format(document=document, chunk=chunk)}],
                temperature=0.0,
                max_tokens=150,
            )
            increment_contextual_retrieval_calls(tokens=response.usage.total_tokens if response.usage else 0)
            return (response.choices[0].message.content or "").strip()
        except Exception as exc:
            logger.warning("[contextual_chunking] Generazione contesto LLM fallita per un chunk: %s", exc)
            return ""


async def generate_chunk_contexts(full_document_text: str, chunks: List[str]) -> List[str]:
    """Genera per ogni chunk una frase di contesto situazionale (contextual retrieval "ricca").

    A differenza della versione economica (solo metadati documento, vedi _build_document_context
    in ingestion.py), qui un LLM legge l'intero documento (troncato a un limite di sicurezza) e il
    singolo chunk per scrivere 1-2 frasi che disambiguano riferimenti impliciti (pronomi, sigle,
    "il sistema precedente", ecc.) prima dell'embedding. Costa una chiamata LLM per chunk: in caso
    di errore o modalità test, il chunk torna a usare solo i metadati documento (stringa vuota).
    """
    if not settings.openai_api_key or settings.openai_api_key.startswith("sk-test"):
        return ["" for _ in chunks]

    truncated_document = full_document_text[: settings.contextual_retrieval_max_doc_chars]
    semaphore = asyncio.Semaphore(settings.contextual_retrieval_concurrency)
    return await asyncio.gather(
        *[_generate_one_context(truncated_document, chunk, semaphore) for chunk in chunks]
    )
