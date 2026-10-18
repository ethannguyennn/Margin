"""MaterialText -> ProcedureDraft: one structured-output Gemini call, then the
deterministic verifier, then one retry for the failing steps only.

A step that still fails after the retry is returned failing, never dropped:
a dropped safety step is worse than a red one in the review screen.

Long materials are split by page ranges with a one-page overlap; each later
call is told the last step already converted so a step never straddles a seam.
Figure images, when the converter has the source bytes, go into the call so
the model can pick the region of a figure that shows a step.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
from typing import Any

from ..pipeline.sanitize import sanitize
from ..pipeline.verify import _get, quote_in_text
from .extract import box_from_2d
from .verify_step import step_failures

log = logging.getLogger("margin.convert")

STRUCTURE_TIMEOUT_S = 120.0
CHUNK_CHARS = 30_000
FIGURE_MAX_PX = 768

SYSTEM_PROMPT = """\
You convert employer instructions into a step-by-step procedure for smart glasses.
Use ONLY the provided MATERIAL. Never add steps, values, tools or warnings that are not in it.
1. One physical action per step, in the order the material gives. Do not merge or reorder.
   If the material numbers its own steps, each numbered step is exactly one step and its label
   is that number (e.g. "3.4"); never split or merge numbered steps. Split only unnumbered prose,
   labelled 1, 2, 3... Headings, scope, tool lists and records are not steps.
2. glance: <= 60 chars, imperative, include the key value + unit. body: <= 450 chars, plain sentences.
3. warning: the material's own warning text for this step, shortened only by deletion, <= 80 chars.
   Never delete "not", "no" or "never". Else an empty string.
4. checkpoint: a measurable acceptance check from the material, <= 60 chars. Else an empty string.
5. quotes: verbatim spans copied from MATERIAL that support every claim in glance, body, warning,
   checkpoint and diagram labels. Copy character for character, including symbols; each quote
   <= 200 chars. Every number, unit and part code you write must appear in one of the quotes.
6. Preserve numbers, units and warnings exactly. Never convert units. Symbols such as a degree
   or micro sign may be written as in the material; the system converts them for the display.
7. diagram: if a FIGURE shows this step, {kind:'crop', figure_id, box_2d of the relevant region
   inside that figure's image as [ymin, xmin, ymax, xmax] normalized to 0-1000 (the whole figure
   is [0, 0, 1000, 1000])}. Else if the material describes a spatial layout for this step
   (positions, order, orientation), {kind:'schematic', elements:[...], alt} using only labels
   present in the quotes: canvas 576 x 144 px (x 0-575, y 0-143); element types line, arrow,
   rect, circle, text, callout (a numbered circle, r 15); labels <= 12 chars; <= 40 elements;
   keep everything inside the canvas. Else kind 'none'. alt: <= 80 chars, what the diagram shows.
8. warnings: the material's general warnings that apply to the whole document, copied verbatim.
Return JSON matching the schema."""

_ELEMENT = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["line", "arrow", "rect", "circle", "text", "callout"]},
        "x": {"type": "integer"}, "y": {"type": "integer"},
        "x2": {"type": "integer"}, "y2": {"type": "integer"}, "r": {"type": "integer"},
        "label": {"type": "string"},
    },
    "required": ["type", "x", "y"],
}
_DIAGRAM = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["none", "crop", "schematic"]},
        "figure_id": {"type": "string"},
        "box_2d": {"type": "array", "items": {"type": "integer"}},
        "elements": {"type": "array", "items": _ELEMENT},
        "alt": {"type": "string"},
    },
    "required": ["kind"],
}
_STEP = {
    "type": "object",
    "properties": {
        "label": {"type": "string"},
        "glance": {"type": "string"},
        "body": {"type": "string"},
        "warning": {"type": "string"},
        "checkpoint": {"type": "string"},
        "quotes": {"type": "array", "items": {"type": "string"}},
        "diagram": _DIAGRAM,
    },
    "required": ["label", "glance", "body", "warning", "checkpoint", "quotes", "diagram"],
}
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {"steps": {"type": "array", "items": _STEP},
                   "warnings": {"type": "array", "items": {"type": "string"}}},
    "required": ["steps", "warnings"],
}


class StructureError(Exception):
    """The structuring call itself failed (timeout, API error, unusable JSON)."""

    code = "llm_timeout"


# --- prompt material ----------------------------------------------------------------------

def material_block(pages: list[Any], figures: list[Any]) -> str:
    parts = ["MATERIAL:"]
    for p in pages:
        parts.append(f"=== PAGE {_get(p, 'page')} ===\n{_get(p, 'text')}")
    if figures:
        parts.append("FIGURES:")
        for f in figures:
            parts.append(f"FIGURE {_get(f, 'figure_id')} (page {_get(f, 'page')}): {_get(f, 'caption') or '(no caption)'}")
    return "\n\n".join(parts)


def chunk_pages(pages: list[Any], limit: int = CHUNK_CHARS) -> list[list[Any]]:
    """Page groups under ``limit`` chars; each later group repeats the previous last page."""
    groups: list[list[Any]] = []
    cur: list[Any] = []
    size = 0
    for p in pages:
        n = len(_get(p, "text") or "")
        if cur and size + n > limit:
            groups.append(cur)
            cur, size = [cur[-1]], len(_get(cur[-1], "text") or "")
        cur.append(p)
        size += n
    if cur:
        groups.append(cur)
    return groups


def figure_images(page_png: dict[int, bytes], figures: list[Any]) -> dict[str, bytes]:
    """PNG of each figure's own region, from page PNGs keyed by page number."""
    from PIL import Image

    out = {}
    for f in figures:
        png = page_png.get(_get(f, "page"))
        if png is None:
            continue
        img = Image.open(io.BytesIO(png))
        x0, y0, x1, y1 = _get(f, "bbox")
        img = img.crop((int(x0 * img.width), int(y0 * img.height), int(x1 * img.width), int(y1 * img.height)))
        img.thumbnail((FIGURE_MAX_PX, FIGURE_MAX_PX))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        out[_get(f, "figure_id")] = buf.getvalue()
    return out


# --- model output -> DraftStep dicts -----------------------------------------------------------

def _clean(text: Any) -> str | None:
    s = " ".join(sanitize(str(text or "")).split())
    return s or None


def to_draft_step(raw: dict, figures: dict[str, Any]) -> dict:
    """One model step -> a DraftStep-shaped dict (sanitized, ``verify`` not yet set)."""
    diagram = None
    d = raw.get("diagram") or {}
    kind = d.get("kind")
    if kind == "crop":
        fid = d.get("figure_id")
        fig = figures.get(fid)
        rel = box_from_2d(d.get("box_2d")) or (0.0, 0.0, 1.0, 1.0)
        bbox = None
        if fig is not None:  # figure-relative box -> page box
            fx0, fy0, fx1, fy1 = (float(v) for v in _get(fig, "bbox"))
            fw, fh = fx1 - fx0, fy1 - fy0
            bbox = tuple(round(v, 4) for v in (fx0 + rel[0] * fw, fy0 + rel[1] * fh,
                                               fx0 + rel[2] * fw, fy0 + rel[3] * fh))
        diagram = {"kind": "crop", "figure_id": fid, "bbox": bbox, "elements": [],
                   "alt": _clean(d.get("alt")) or _clean(_get(fig, "caption") if fig else "") or "Figure"}
    elif kind == "schematic":
        elements = []
        for e in d.get("elements") or []:
            el = {k: e.get(k) for k in ("type", "x", "y", "x2", "y2", "r")}
            el["label"] = _clean(e.get("label"))
            elements.append(el)
        diagram = {"kind": "schematic", "figure_id": None, "bbox": None, "elements": elements,
                   "alt": _clean(d.get("alt")) or "Diagram"}
    return {
        "label": str(raw.get("label") or "").strip(),
        "glance": _clean(raw.get("glance")) or "",
        "body": _clean(raw.get("body")) or "",
        "warning": _clean(raw.get("warning")),
        "checkpoint": _clean(raw.get("checkpoint")),
        "quotes": [q for q in (str(x).strip() for x in raw.get("quotes") or []) if q],
        "diagram": diagram,
        "diagram_id": None,
        "diagram_approved": False,
    }


def _verified(step: dict, text: Any) -> dict:
    reasons = step_failures(step, text)
    step["verify"] = {"ok": not reasons, "reason": "; ".join(reasons) or None, "citations": []}
    return step


# --- the Gemini structurer --------------------------------------------------------------------

class GeminiStructurer:
    def __init__(self, client: Any, model: str, timeout: float = STRUCTURE_TIMEOUT_S):
        if not model:
            raise ValueError("GEMINI_MODEL_CONVERT is not set")
        self.client, self.model, self.timeout = client, model, timeout
        self.calls = 0

    async def call(self, prompt: str, images: dict[str, bytes]) -> dict:
        """One structured-output request. Never logs the prompt (it holds material text)."""
        from google.genai import types

        self.calls += 1
        contents: list[Any] = []
        for fid, png in images.items():
            contents += [f"FIGURE {fid} image:", types.Part.from_bytes(data=png, mime_type="image/png")]
        contents.append(prompt)
        try:
            resp = await asyncio.wait_for(
                self.client.aio.models.generate_content(
                    model=self.model, contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT, temperature=0.1,
                        response_mime_type="application/json", response_json_schema=RESPONSE_SCHEMA),
                ),
                timeout=self.timeout,
            )
            out = json.loads(resp.text or "")
        except asyncio.TimeoutError as e:
            raise StructureError("structuring timed out") from e
        except Exception as e:
            raise StructureError(f"structuring failed: {type(e).__name__}") from e
        if not isinstance(out, dict) or not isinstance(out.get("steps"), list):
            raise StructureError("structuring returned no steps")
        return out


async def convert_dict(text: Any, doc_id: str, revision: str, title: str, structurer: Any,
                       images: dict[str, bytes] | None = None) -> dict:
    """The conversion as a plain dict shaped like ``ProcedureDraft``."""
    pages = list(_get(text, "pages") or [])
    figures = {_get(f, "figure_id"): f for f in _get(text, "figures") or []}
    images = images or {}
    head = f"PROCEDURE: {doc_id} rev {revision} - {title}\n\n"

    raw_steps: list[dict] = []
    doc_warnings: list[str] = []
    for i, group in enumerate(chunk_pages(pages)):
        nums = {_get(p, "page") for p in group}
        figs = [f for f in figures.values() if _get(f, "page") in nums]
        seam = ""
        if raw_steps:
            last = raw_steps[-1]
            seam = (f"\n\nSteps from earlier pages are already converted; the last one is "
                    f"{last.get('label')}: {last.get('glance')}. Return only steps that come after it.")
        out = await structurer.call(head + material_block(group, figs) + seam,
                                    {k: v for k, v in images.items() if k in {_get(f, 'figure_id') for f in figs}})
        seen = {s.get("label") for s in raw_steps}
        raw_steps += [s for s in out["steps"] if isinstance(s, dict) and s.get("label") not in seen]
        doc_warnings += [w for w in out.get("warnings") or [] if isinstance(w, str)]

    steps = [_verified(to_draft_step(s, figures), text) for s in raw_steps]

    failing = [s for s in steps if not s["verify"]["ok"]]
    if failing:
        reasons = "\n".join(f"- step {s['label']}: {s['verify']['reason']}" for s in failing)
        prompt = (head + material_block(pages, list(figures.values())) +
                  "\n\nThese steps failed verification against the MATERIAL:\n" + reasons +
                  "\n\nReturn corrected versions of ONLY these steps, with the same labels. Fix every listed "
                  "problem using verbatim quotes. If a value cannot be supported by a verbatim quote, remove "
                  "the value; never invent one.")
        try:
            retry = await structurer.call(prompt, images)
            fixed = {str(s.get("label") or "").strip(): s for s in retry["steps"] if isinstance(s, dict)}
        except StructureError as e:
            log.warning("structuring retry failed: %s", e)
            fixed = {}
        for i, s in enumerate(steps):
            if not s["verify"]["ok"] and s["label"] in fixed:
                steps[i] = _verified(to_draft_step(fixed[s["label"]], figures), text)

    material = "\n".join(_get(p, "text") or "" for p in pages)
    kept = [w for w in dict.fromkeys(_clean(w) for w in doc_warnings) if w and quote_in_text(w, material)]
    if len(kept) < len(set(doc_warnings)):
        log.info("dropped %d document warning(s) not found verbatim in the material", len(set(doc_warnings)) - len(kept))
    return {
        "doc_id": doc_id, "revision": revision, "title": title,
        "material_id": _get(text, "material_id"),
        "status": "ready" if steps else "failed",
        "steps": steps, "warnings": kept,
    }


# --- the Converter Protocol -----------------------------------------------------------------------

class GeminiConverter:
    """``Converter``: extract() then convert(). Keeps the last few materials' bytes
    (by material_id) so convert() can show the model the figures it may crop."""

    def __init__(self, client: Any, model: str, keep: int = 8):
        from .extract import GeminiReader

        self.reader = GeminiReader(client, model)
        self.structurer = GeminiStructurer(client, model)
        self._sources: dict[str, tuple[bytes, str]] = {}
        self._keep = keep

    @classmethod
    def from_settings(cls, settings: Any, client: Any = None) -> "GeminiConverter":
        from ..pipeline.generate import gemini_client

        model = getattr(settings, "gemini_model_convert", "")
        return cls(client or gemini_client(settings.gemini_api_key), model)

    async def extract(self, data: bytes, mime: str, material_id: str):
        from ..schemas import MaterialText
        from .extract import extract_dict

        self._sources[material_id] = (data, mime)
        while len(self._sources) > self._keep:
            self._sources.pop(next(iter(self._sources)))
        return MaterialText.model_validate(await extract_dict(data, mime, material_id, self.reader))

    def figure_images(self, text: Any) -> dict[str, bytes]:
        source = self._sources.get(_get(text, "material_id"))
        figures = list(_get(text, "figures") or [])
        if source is None or not figures:
            return {}
        from ..diagrams.render import page_image

        data, mime = source
        pngs = {}
        for page in {_get(f, "page") for f in figures}:
            try:
                pngs[page] = page_image(data, mime, page)
            except ValueError:
                continue
        return figure_images(pngs, figures)

    async def convert(self, text: Any, doc_id: str, revision: str, title: str):
        from ..schemas import ProcedureDraft

        draft = await convert_dict(text, doc_id, revision, title, self.structurer, self.figure_images(text))
        return ProcedureDraft.model_validate(draft)
