"""bytes -> MaterialText: what the material says, verbatim, per page, plus figures.

This is what the supervisor reviews and what every quote is checked against,
so it must be faithful, not pretty.

| Input            | Text                                      | Figures                                   |
| markdown / text  | as is                                     | none                                      |
| DOCX             | python-docx paragraphs + tables -> md     | embedded images, bbox = whole image       |
| PDF, text layer  | pypdf per page                            | Gemini on pages that contain an image     |
| PDF page w/o text, PNG, JPEG | Gemini verbatim transcription | the same call                             |

Gemini prompts demand verbatim text and ``[illegible]`` for anything
unreadable. A page whose call fails or times out becomes
``[page N failed to read]``, which makes any step quoting it fail
verification. Never guess.

Page numbering is 1-based. DOCX has no pages: all text is page 1, and figure
k has ``page = k`` meaning "the k-th embedded image" (``render.page_image``
uses the same convention).
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
from typing import Any

log = logging.getLogger("margin.convert")

EXTRACT_TIMEOUT_S = 90.0  # gemini-3.7-flash took > 60 s on a figure page; conversion is a background job
RENDER_DPI = 150
MIME_PDF = "application/pdf"
MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MIME_TEXT = ("text/markdown", "text/plain", "text/x-markdown")
MIME_IMAGE = ("image/png", "image/jpeg")

ILLEGIBLE = "[illegible]"

TRANSCRIBE_PROMPT = """\
Transcribe the printed text of this page verbatim as markdown, in reading order.
Rules:
1. Copy every word, number, unit, symbol and warning exactly as printed. Do not summarise,
   reorder, translate, expand abbreviations, convert units or fix typos.
2. Write any text you cannot read with certainty as [illegible]. Never guess a value.
3. Use markdown only for structure that is printed (headings, numbered lists, tables).
4. Text that is part of a drawing (labels inside a figure) is not page text; figure captions
   printed under or over a figure are page text.
5. figures: every drawing, diagram, photo or chart on the page, with box_2d as
   [ymin, xmin, ymax, xmax] normalized to 0-1000, and its printed caption copied verbatim
   (empty if none). Return an empty list if there are none."""

FIGURES_PROMPT = """\
List every drawing, diagram, photo or chart on this page. For each, return box_2d as
[ymin, xmin, ymax, xmax] normalized to 0-1000 around the whole figure, and the caption
printed with it copied verbatim (empty if none). Do not transcribe anything else.
Return an empty list if there are no figures."""

_FIGURE_ITEMS = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "box_2d": {"type": "array", "items": {"type": "integer"}},
            "caption": {"type": "string"},
        },
        "required": ["box_2d", "caption"],
    },
}
PAGE_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string"}, "figures": _FIGURE_ITEMS},
    "required": ["text", "figures"],
}
FIGURES_SCHEMA = {"type": "object", "properties": {"figures": _FIGURE_ITEMS}, "required": ["figures"]}


class ExtractionError(Exception):
    """The material as a whole cannot be read (unsupported type, corrupt file)."""

    code = "bad_request"


def failed_page(n: int) -> str:
    return f"[page {n} failed to read]"


def _mime(mime: str) -> str:
    return (mime or "").split(";")[0].strip().lower()


# --- deterministic paths ----------------------------------------------------------------

def text_pages(data: bytes) -> list[str]:
    try:
        return [data.decode("utf-8-sig")]
    except UnicodeDecodeError as e:
        raise ExtractionError("text material is not UTF-8") from e


def _docx_document(data: bytes):
    from docx import Document

    try:
        return Document(io.BytesIO(data))
    except Exception as e:
        raise ExtractionError(f"DOCX could not be opened: {type(e).__name__}") from e


_BLIP = "{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
_EMBED = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"


def docx_images(data: bytes) -> list[bytes]:
    """Embedded images in document order (inline pictures)."""
    doc = _docx_document(data)
    out = []
    for blip in doc.element.body.iter(_BLIP):
        rid = blip.get(_EMBED)
        part = doc.part.related_parts.get(rid)
        if part is not None:
            out.append(part.blob)
    return out


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def docx_markdown(data: bytes) -> tuple[str, list[str]]:
    """(markdown of every paragraph and table in body order, caption per embedded image)."""
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = _docx_document(data)
    lines: list[str] = []
    captions: list[str] = []
    pending: int | None = None  # index of the last image still waiting for its caption
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            para = Paragraph(child, doc)
            if any(True for _ in child.iter(_BLIP)):
                captions.append("")
                pending = len(captions) - 1
            text = para.text
            if not text.strip():
                continue
            style = (para.style.name or "") if para.style is not None else ""
            m = re.match(r"Heading (\d)", style)
            if m:
                lines.append("#" * int(m.group(1)) + " " + text)
            elif style == "Title":
                lines.append("# " + text)
            else:
                lines.append(text)
            if pending is not None and re.match(r"(?i)fig(ure)?\.?\s*\d", text.strip()):
                captions[pending] = text.strip()
                pending = None
        elif tag == "tbl":
            rows = [[_cell(c.text) for c in r.cells] for r in Table(child, doc).rows]
            if rows:
                lines.append("| " + " | ".join(rows[0]) + " |")
                lines.append("|" + " --- |" * len(rows[0]))
                lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n\n".join(lines), captions


def pdf_pages(data: bytes) -> list[tuple[str, bool]]:
    """(text layer, page has an embedded image) per page."""
    import pypdf

    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        out = []
        for page in reader.pages:
            try:
                has_image = len(page.images) > 0
            except Exception:  # an unreadable image stream still means "there is a figure"
                has_image = True
            out.append(((page.extract_text() or "").strip(), has_image))
        return out
    except Exception as e:
        raise ExtractionError(f"PDF could not be read: {type(e).__name__}") from e


def pdf_page_png(data: bytes, page: int) -> bytes:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    try:
        img = pdf[page - 1].render(scale=RENDER_DPI / 72).to_pil()
    finally:
        pdf.close()
    buf = io.BytesIO()
    img.convert("L").save(buf, "PNG")
    return buf.getvalue()


def box_from_2d(box: Any) -> tuple[float, float, float, float] | None:
    """Gemini ``[ymin, xmin, ymax, xmax]`` in 0..1000 -> contract ``(x0, y0, x1, y1)`` in 0..1."""
    try:
        ymin, xmin, ymax, xmax = (min(1000, max(0, int(v))) / 1000 for v in box)
    except (TypeError, ValueError):
        return None
    if xmax <= xmin or ymax <= ymin:
        return None
    return (xmin, ymin, xmax, ymax)


# --- Gemini --------------------------------------------------------------------------------

class GeminiReader:
    """One structured-output vision call per page. Never logs page content."""

    def __init__(self, client: Any, model: str, timeout: float = EXTRACT_TIMEOUT_S):
        if not model:
            raise ValueError("GEMINI_MODEL_CONVERT is not set")
        self.client, self.model, self.timeout = client, model, timeout
        self.calls = 0

    async def _call(self, image: bytes, mime: str, prompt: str, schema: dict) -> dict:
        import json

        from google.genai import types

        self.calls += 1
        resp = await asyncio.wait_for(
            self.client.aio.models.generate_content(
                model=self.model,
                contents=[types.Part.from_bytes(data=image, mime_type=mime), prompt],
                config=types.GenerateContentConfig(
                    temperature=0.0, response_mime_type="application/json", response_json_schema=schema),
            ),
            timeout=self.timeout,
        )
        return json.loads(resp.text or "{}")

    async def transcribe(self, image: bytes, mime: str) -> dict:
        return await self._call(image, mime, TRANSCRIBE_PROMPT, PAGE_SCHEMA)

    async def figures(self, image: bytes, mime: str) -> dict:
        return await self._call(image, mime, FIGURES_PROMPT, FIGURES_SCHEMA)


async def _read_page(reader: GeminiReader | None, n: int, image: bytes, mime: str,
                     text: str | None) -> tuple[str, list[dict]]:
    """Page text (the text layer when given, else a transcription) and its figures."""
    if reader is None:
        if text is None:
            log.warning("page %d has no text layer and no Gemini reader is configured", n)
            return failed_page(n), []
        return text, []
    try:
        if text is None:
            out = await reader.transcribe(image, mime)
            page_text = out.get("text")
            if not isinstance(page_text, str):
                raise ValueError("no text in the transcription")
        else:
            out = await reader.figures(image, mime)
            page_text = text
    except Exception as e:  # timeout, API or JSON error: never guess
        log.warning("page %d failed to read: %s", n, type(e).__name__)
        return (failed_page(n) if text is None else text), []
    figures = []
    for f in out.get("figures") or []:
        box = box_from_2d(f.get("box_2d"))
        if box is not None:
            figures.append({"page": n, "bbox": box, "caption": str(f.get("caption") or "").strip()})
    return page_text, figures


async def extract(data: bytes, mime: str, material_id: str, reader: GeminiReader | None = None):
    """Protocol ``Converter.extract``: returns Part 3's ``MaterialText``."""
    from ..schemas import MaterialText

    return MaterialText.model_validate(await extract_dict(data, mime, material_id, reader))


async def extract_dict(data: bytes, mime: str, material_id: str, reader: GeminiReader | None = None) -> dict:
    """Same as :func:`extract`, as a plain dict (no schema dependency)."""
    kind = _mime(mime)
    pages: list[dict] = []
    figures: list[dict] = []
    if kind in MIME_TEXT:
        pages = [{"page": 1, "text": t} for t in text_pages(data)]
    elif kind == MIME_DOCX:
        text, captions = docx_markdown(data)
        pages = [{"page": 1, "text": text}]
        figures = [{"page": k, "bbox": (0.0, 0.0, 1.0, 1.0), "caption": c} for k, c in enumerate(captions, 1)]
    elif kind == MIME_PDF:
        layer = pdf_pages(data)
        jobs = []
        for n, (text, has_image) in enumerate(layer, start=1):
            if text and not has_image:
                jobs.append(asyncio.sleep(0, result=(text, [])))
            else:
                jobs.append(_read_page(reader, n, pdf_page_png(data, n), "image/png", text or None))
        for n, (text, figs) in enumerate(await asyncio.gather(*jobs), start=1):
            pages.append({"page": n, "text": text})
            figures += figs
    elif kind in MIME_IMAGE:
        text, figs = await _read_page(reader, 1, data, kind, None)
        pages, figures = [{"page": 1, "text": text}], figs
    else:
        raise ExtractionError(f"unsupported material type {mime!r}")
    for i, f in enumerate(figures, start=1):
        f["figure_id"] = f"F{i}"
    return {"material_id": material_id, "pages": pages, "figures": figures}
