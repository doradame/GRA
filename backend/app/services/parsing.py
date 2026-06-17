import io
import logging
from dataclasses import dataclass
from typing import List
import magic
from pypdf import PdfReader
from docx import Document as DocxDocument
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class ParsingResult:
    text: str
    mime_type: str
    parser: str
    page_count: int | None = None
    ocr_used: bool = False


def extract_text(filename: str, data: bytes) -> str:
    return extract_document(filename, data).text


def extract_document(
    filename: str,
    data: bytes,
    enable_ocr: bool = False,
    min_text_chars_for_ocr: int = 100,
) -> ParsingResult:
    mime = magic.from_buffer(data, mime=True)
    lower_name = filename.lower()

    if mime == "application/pdf" or lower_name.endswith(".pdf"):
        text, page_count = _extract_pdf(data)
        if enable_ocr and len(text.strip()) < min_text_chars_for_ocr:
            ocr_text = _extract_pdf_ocr(data)
            if ocr_text.strip():
                return ParsingResult(
                    text=ocr_text,
                    mime_type=mime,
                    parser="pdf_ocr",
                    page_count=page_count,
                    ocr_used=True,
                )
        return ParsingResult(text=text, mime_type=mime, parser="pypdf", page_count=page_count)
    if mime in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    ) or lower_name.endswith((".docx", ".doc")):
        text = _extract_docx(data)
        return ParsingResult(text=text, mime_type=mime, parser="python-docx")
    if mime.startswith("text/") or lower_name.endswith((".txt", ".md", ".csv", ".json")):
        return ParsingResult(text=data.decode("utf-8", errors="ignore"), mime_type=mime, parser="text")
    if mime == "text/html" or lower_name.endswith((".html", ".htm")):
        return ParsingResult(text=_extract_html(data), mime_type=mime, parser="beautifulsoup")

    # Fallback: prova come testo
    return ParsingResult(text=data.decode("utf-8", errors="ignore"), mime_type=mime, parser="text_fallback")


def _extract_pdf(data: bytes) -> tuple[str, int]:
    reader = PdfReader(io.BytesIO(data))
    parts: List[str] = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            parts.append(text)
    return "\n\n".join(parts), len(reader.pages)


def _extract_pdf_ocr(data: bytes) -> str:
    try:
        import pypdfium2 as pdfium  # type: ignore
        import pytesseract  # type: ignore
    except Exception as exc:
        logger.warning("OCR requested but optional OCR dependencies are unavailable: %s", exc)
        return ""

    parts: List[str] = []
    pdf = pdfium.PdfDocument(data)
    try:
        for page_index in range(len(pdf)):
            page = pdf[page_index]
            bitmap = page.render(scale=2).to_pil()
            text = pytesseract.image_to_string(bitmap)
            if text.strip():
                parts.append(text)
    finally:
        pdf.close()
    return "\n\n".join(parts)


def _extract_docx(data: bytes) -> str:
    doc = DocxDocument(io.BytesIO(data))
    parts: List[str] = []
    for para in doc.paragraphs:
        if para.text.strip():
            parts.append(para.text)
    return "\n\n".join(parts)


def _extract_html(data: bytes) -> str:
    soup = BeautifulSoup(data, "html.parser")
    for script in soup(["script", "style"]):
        script.decompose()
    return soup.get_text(separator="\n")
