"""Mock pipeline + mock DB for MOCK_MODE=1 (and per-component fallback).

No network, no database, no API key. The mock corpus is a tiny synthetic
stand-in for Part 5's real one, shaped so ``/v1/ask`` returns the same fixture
set Part 2 mocks on the app side:

  "how tight" / "torque" / "m5"   -> answered, SOP-114 Sec 4.2 rev C, verified
  "guide me" / "walk me through"  -> walkthrough, 7 steps
  "clean" / "disinfect"           -> answered, SOP-120, long (2-page) body
  "coffee" / anything unmatched   -> not_found (retrieval gate, no LLM call)
  "log deviation"                 -> logged
  "boom"                          -> error, llm_timeout

The mocks run through the real ``/v1/ask`` orchestration, so the gate, the
verify/retry path, sanitizing and source assembly are exercised in mock mode too.

v2 (BUILD-PLAN-V2): ``parse_command``, an in-memory ``MockDB`` with every Part 5
v2 query (materials, drafts, diagrams, devices, assignments, progress, publish),
``MockConverter`` + ``verify_step`` (text uploads are converted for real;
binary uploads get a clearly labelled synthetic stand-in), and ``MockRenderer``
(stdlib 8-bit grey PNG tiles, the proven lens format; no Pillow). SOP-114 rev C step 4.2 ships with an approved demo
schematic (DGM-0001, the star torque order) so "show diagram" works on the mock
relay for milestone M2.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import math
import re
import struct
import zlib
from datetime import datetime, timedelta, timezone
from typing import Any

from .. import obs
from ..schemas import (
    ANSWER_BODY_MAX,
    ANSWER_GLANCE_MAX,
    BODY_MAX,
    CHECKPOINT_MAX,
    DIAGRAM_ALT_MAX,
    DIAGRAM_ELEMENTS_MAX,
    DIAGRAM_LABEL_MAX,
    GLANCE_MAX,
    WARNING_MAX,
    Chunk,
    Citation,
    Diagram,
    DiagramElement,
    DiagramSpec,
    Draft,
    DraftCitation,
    DraftStep,
    Intent,
    IntentResult,
    MaterialText,
    PageText,
    Procedure,
    ProcedureDraft,
    ProgressEvent,
    RetrievalResult,
    Step,
    VerifyResult,
)
from . import LlmTimeout

log = logging.getLogger("specs.mock")

# Thresholds the gate uses in mock mode when NOT_FOUND_MIN_* are unset.
MOCK_MIN_SIM = 0.5
MOCK_MIN_RRF = 0.02

MOCK_TRANSCRIPT = "how tight is the m5 on the mounting bracket"


def _c(doc_id: str, rev: str, section: str, heading: str, text: str, title: str,
       step_order: int | None = None) -> Chunk:
    return Chunk(chunk_id=f"{doc_id}:{rev}:{section}", doc_id=doc_id, revision=rev,
                 section=section, heading=heading, text=text, title=title,
                 is_step=step_order is not None, step_order=step_order)


_T114 = "Mounting Bracket Assembly"
_T120 = "Cleaning and Disinfection"

# Text copied from Part 5's synthetic corpus (corpus/SOP-114-C.md, SOP-120-B.md) so
# mock answers read like real ones. SOP-120 keeps its degree/micro glyphs on purpose.
MOCK_CHUNKS: list[Chunk] = [
    _c("SOP-114", "C", "4.1", "Prepare and seat the bracket",
       "Disconnect power. Confirm the green RECEIVED label from SOP-101. Check the torque "
       "wrench under SOP-131. Seat bracket HX2-210 with the arrow toward the outlet. Fit all "
       "four washers and start all four M5 screws by hand for 3 full turns. Keep threads dry.",
       _T114, 1),
    _c("SOP-114", "C", "4.2", "Fasten the M5 bracket screws",
       "Torque all four M5 bracket screws to 4 N-m in a star pattern using a calibrated torque "
       "wrench (see SOP-131). Tighten in the order upper left, lower right, upper right, lower "
       "left. Stop at the first click on each screw; do not click twice.", _T114, 2),
    _c("SOP-114", "C", "4.3", "Check the bracket gap",
       "Check the gap between the bracket foot and housing with a 0.20 mm feeler gauge. The "
       "gauge must not enter at any of the four screw positions. If it enters, stop and report "
       "the gap under SOP-140; do not add torque.", _T114, 3),
    _c("SOP-114", "C", "4.4", "Apply witness marks",
       "Apply one blue witness line across each screw head and onto the bracket. Each line must "
       "be continuous and visible from the front. Do not mark the pump serial label.", _T114, 4),
    _c("SOP-114", "C", "4.5", "Check outlet clearance",
       "Measure the clearance between the bracket edge and outlet collar. Accept at least 6 mm "
       "clearance. Route the disconnected power lead outside the bracket opening without "
       "pinching it.", _T114, 5),
    _c("SOP-114", "C", "4.6", "Record assembly",
       "Record the pump serial number, wrench asset number, 4 N-m setting, and assembler "
       "initials on assembly form AS-114. Record revision C. Do not record a measured torque "
       "when only a wrench setting was used.", _T114, 6),
    _c("SOP-114", "C", "4.7", "Release to the next station",
       "Confirm all four witness marks and the completed AS-114. Place the pump in the "
       "ASSEMBLED tray. Keep power disconnected; this procedure does not authorize a powered "
       "run test.", _T114, 7),
    _c("SOP-120", "B", "4.1", "Isolate and cool",
       "Disconnect power and remove the pump from the training fixture. Allow the housing to "
       "cool below 35 °C before wiping. Keep the outlet cap installed throughout cleaning.",
       _T120, 1),
    _c("SOP-120", "B", "4.2", "Remove visible soil",
       "Dampen a lint-free cloth with water filtered through a 5 µm filter. Wipe visible "
       "soil from the external housing until no residue remains. Do not allow free liquid to "
       "run into seams or connectors.", _T120, 2),
    _c("SOP-120", "B", "4.3", "Disinfect the housing",
       "Wipe the external housing with a premixed 70 % isopropyl alcohol wipe. Keep the surface "
       "visibly wet for 60 s. Use a fresh wipe if the surface dries before the contact time "
       "ends. Do not dilute the premixed wipe.", _T120, 3),
    _c("SOP-120", "B", "4.4", "Air dry",
       "Allow the housing to air dry for at least 5 min after the contact time. Do not use "
       "compressed air, heat, or a dry cloth to shorten drying. Leave power disconnected during "
       "drying.", _T120, 4),
]

# keyword -> RRF-ordered hits. "walk me through"/"guide me" questions also mention the
# bracket, so the walkthrough resolves to SOP-114 through the same table.
_TOPICS: list[tuple[re.Pattern[str], list[str]]] = [
    (re.compile(r"clean|disinfect"), ["SOP-120:B:4.3", "SOP-120:B:4.4"]),
    (re.compile(r"how tight|torque|\bm5\b|bracket|mounting|guide me|walk me through|boom"),
     ["SOP-114:C:4.2", "SOP-114:C:4.1"]),
]

# --- intent / sanitize (stand-ins until Part 4's real modules land) ----------

_INTENT_RULES: list[tuple[Intent, re.Pattern[str]]] = [
    ("walkthrough", re.compile(r"guide me|walk me through|step by step|take me through|start procedure", re.I)),
    ("deviation", re.compile(r"log (a )?deviation|report (an )?(issue|problem|nonconformance)|flag this", re.I)),
    ("repeat", re.compile(r"\brepeat\b|say that again|^\s*what was that\s*\??\s*$", re.I)),
]


# BUILD-PLAN-V2 section 3, verbatim. Stand-in for Part 4's parse_command.
COMMAND_PHRASES: dict[str, tuple[str, ...]] = {
    "next": ("next", "done", "next step", "finished", "complete"),
    "back": ("back", "previous", "go back"),
    "repeat": ("repeat", "say that again"),
    "details": ("details", "more", "read it"),
    "diagram": ("diagram", "show diagram", "picture", "show me"),
    "pause": ("pause", "stop task"),
    "resume": ("resume", "continue"),
    "exit": ("exit", "close specs"),
}
_PHRASE_TO_COMMAND = {p: c for c, ps in COMMAND_PHRASES.items() for p in ps}
_FILLER = frozenset({"ok", "okay", "um", "uh", "please", "specs", "hey"})


def parse_command(transcript: str | None) -> str | None:
    """The command if the *whole* utterance (filler stripped from the ends) is one."""
    words = re.findall(r"[a-z]+", (transcript or "").lower())
    lo, hi = 0, len(words)
    while lo < hi:
        hit = _PHRASE_TO_COMMAND.get(" ".join(words[lo:hi]))
        if hit:
            return hit
        if words[lo] in _FILLER:
            lo += 1
        elif words[hi - 1] in _FILLER:
            hi -= 1
        else:
            return None
    return None


def classify_intent(transcript: str) -> IntentResult:
    if not transcript.strip():
        return IntentResult(intent="unknown", text="")
    if parse_command(transcript):
        return IntentResult(intent="command", text=transcript)
    for intent, pattern in _INTENT_RULES:
        match = pattern.search(transcript)
        if match:
            rest = (transcript[: match.start()] + transcript[match.end():]).strip(" ,.:;-")
            return IntentResult(intent=intent, text=rest if intent == "deviation" else transcript)
    return IntentResult(intent="question", text=transcript)


def sanitize(text: str) -> str:
    """Crude stand-in: ASCII only. Part 4's sanitize.py owns the real glyph table."""
    return text.encode("ascii", "ignore").decode("ascii")


def verify(draft: Draft, chunks: list[Chunk]) -> VerifyResult:
    """Stand-in verifier: cited chunk must be retrieved and quote must be a substring."""
    by_id = {c.chunk_id: c for c in chunks}
    resolved: list[Citation] = []
    if not draft.citations:
        return VerifyResult(ok=False, reason="no citations")
    for cit in draft.citations:
        chunk = by_id.get(cit.chunk_id)
        if chunk is None:
            return VerifyResult(ok=False, reason=f"cited chunk {cit.chunk_id} was not retrieved")
        if " ".join(cit.quote.lower().split()) not in " ".join(chunk.text.lower().split()):
            return VerifyResult(ok=False, reason=f"quote not found in {cit.chunk_id}")
        resolved.append(Citation(chunk_id=chunk.chunk_id, doc_id=chunk.doc_id,
                                 revision=chunk.revision, section=chunk.section, quote=cit.quote))
    return VerifyResult(ok=True, citations=resolved)


# --- components ----------------------------------------------------------------


class MockTranscriber:
    async def transcribe(self, pcm: bytes, sample_rate: int) -> str:
        await asyncio.sleep(0.02)
        return MOCK_TRANSCRIPT


def _fit(text: str, limit: int) -> str:
    """Mock-only: clip fixture text at a word boundary so mock steps respect the caps."""
    if len(text) <= limit:
        return text
    return text[: limit - 3].rsplit(" ", 1)[0] + "..."


class MockRetriever:
    """Keyword retrieval over the mock corpus. Given a MockDB it shares its chunks,
    document statuses and v2 step extras, so published drafts and the demo diagram
    show up in walkthroughs and assignments."""

    def __init__(self, chunks: list[Chunk] | None = None, db: MockDB | None = None) -> None:
        self.db = db
        if db is not None:
            self.chunks = db.chunks
        else:
            self.chunks = list(chunks) if chunks is not None else list(MOCK_CHUNKS)
        self.calls = 0

    async def embed(self, query: str) -> list[float]:
        await asyncio.sleep(0.005)
        return [0.0]

    async def retrieve(self, query: str, revision: str | None,
                       q_embedding: list[float] | None = None) -> RetrievalResult:
        self.calls += 1
        if q_embedding is None:
            with obs.stage("embed"):
                await self.embed(query)
        await asyncio.sleep(0.005)
        q = query.lower()
        by_id = {c.chunk_id: c for c in self.chunks}
        hits: list[str] = []
        for pattern, ids in _TOPICS:
            if pattern.search(q):
                hits = ids
                break
        if not hits:
            return RetrievalResult(chunks=[], best_sim=0.12, best_rrf=0.004)
        ranked = [by_id[i].model_copy(update={"sim": 0.86 - 0.1 * n, "rrf": 1 / (61 + n) * 2})
                  for n, i in enumerate(hits) if i in by_id]
        if revision:
            ranked = [c for c in ranked if c.revision == revision]
        if not ranked:
            return RetrievalResult(chunks=[], best_sim=0.12, best_rrf=0.004)
        return RetrievalResult(chunks=ranked, best_sim=ranked[0].sim or 0.0,
                               best_rrf=ranked[0].rrf or 0.0)

    async def steps_for(self, doc_id: str, revision: str | None) -> list[Step]:
        if revision is None and self.db is not None:
            revision = self.db.effective_revision(doc_id)
            if revision is None:
                return []
        steps = [c for c in self.chunks if c.doc_id == doc_id and c.is_step
                 and (revision is None or c.revision == revision)]
        steps.sort(key=lambda c: c.step_order or 0)
        extras = self.db.step_extras if self.db is not None else {}
        out = []
        for c in steps:
            extra = extras.get(c.chunk_id, {})
            out.append(Step(
                step_id=c.chunk_id, label=c.section,
                glance=extra.get("glance") or _fit(f"{c.section} {c.heading or ''}".strip(), GLANCE_MAX),
                body=extra.get("body") or _fit(c.text, BODY_MAX),
                warning=extra.get("warning"), checkpoint=extra.get("checkpoint"),
                diagram=extra.get("diagram")))
        return out


class MockGenerator:
    """Extractive stand-in: body is verbatim text of the top chunks of the top document,
    each cited in full, so it passes any honest verifier. 'boom' simulates an LLM timeout."""

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, query: str, chunks: list[Chunk], feedback: str | None = None) -> Draft:
        self.calls += 1
        await asyncio.sleep(0.02)
        if "boom" in query.lower():
            raise LlmTimeout("mock generator timed out (boom)")
        if not chunks:
            return Draft(answerable=False)
        top = chunks[0]
        # Leading whole sentences of the top chunk within the answer limit. The citation
        # quotes the whole chunk, so every number in glance or body is covered.
        body = ""
        for sentence in _SENTENCE.split(top.text):
            joined = f"{body} {sentence}".strip()
            if len(joined) > ANSWER_BODY_MAX:
                break
            body = joined
        if top.chunk_id == "SOP-114:C:4.2":
            glance = "Torque M5 to 4 N-m"
        else:
            glance = (top.heading or top.doc_id)[:ANSWER_GLANCE_MAX]
        return Draft(answerable=True, glance=glance, body=body,
                     citations=[DraftCitation(chunk_id=top.chunk_id, quote=top.text)])


class MockNotifier:
    async def notify(self, deviation_id: str, text: str) -> bool:
        log.info("MOCK notify supervisor: %s", deviation_id)
        return True


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ms(value: datetime) -> float:
    return value.timestamp() * 1000.0


class MockDB:
    """In-memory stand-in for Part 5's db module: same function names, same
    semantics and the same exception types (LookupError / ValueError)."""

    def __init__(self, chunks: list[Chunk] | None = None) -> None:
        self.chunks: list[Chunk] = list(chunks) if chunks is not None else list(MOCK_CHUNKS)
        self.documents: dict[tuple[str, str], dict[str, Any]] = {}
        for c in self.chunks:
            self.documents.setdefault((c.doc_id, c.revision), {
                "doc_id": c.doc_id, "revision": c.revision, "title": c.title or c.doc_id,
                "status": "effective"})
        self.step_extras: dict[str, dict[str, Any]] = {}  # chunk_id -> v2 Step fields
        self.events: list[dict[str, Any]] = []
        self.deviations: list[dict[str, Any]] = []
        self.materials: dict[str, dict[str, Any]] = {}
        self.drafts: dict[tuple[str, str], dict[str, Any]] = {}
        self.diagrams: dict[str, dict[str, Any]] = {}
        self.devices: dict[str, dict[str, Any]] = {}
        self.assignments: dict[str, dict[str, Any]] = {}
        self.progress: dict[tuple[str, str, str, float], dict[str, Any]] = {}
        self._dev_seq = itertools.count(1)
        self._seq = {k: itertools.count(1) for k in ("MAT", "DGM", "LNS", "ASN")}
        self._seed_demo()

    def _next(self, prefix: str) -> str:
        return f"{prefix}-{next(self._seq[prefix]):04d}"

    def _seed_demo(self) -> None:
        """v2 extras on the mock SOP-114 rev C, including the approved demo diagram."""
        if ("SOP-114", "C") not in self.documents:
            return
        self.step_extras["SOP-114:C:4.1"] = {"warning": "Isolate power before assembly."}
        self.step_extras["SOP-114:C:4.3"] = {"checkpoint": "0.20 mm gauge must not enter"}
        renderer = MockRenderer()
        tiles = renderer.render(DEMO_SPEC, None)
        diagram_id = self._next("DGM")
        self.diagrams[diagram_id] = {
            "diagram_id": diagram_id, "doc_id": "SOP-114", "revision": "C", "step_label": "4.2",
            "spec": DEMO_SPEC.model_dump(mode="json"), "tiles": tiles,
            "preview_png": renderer.preview_png(tiles), "approved": True}
        self.step_extras["SOP-114:C:4.2"] = {"diagram": Diagram(
            diagram_id=diagram_id, width=576, height=144, alt=DEMO_SPEC.alt)}

    def effective_revision(self, doc_id: str) -> str | None:
        return next((rev for (doc, rev), d in self.documents.items()
                     if doc == doc_id and d["status"] == "effective"), None)

    # --- v1 ---------------------------------------------------------------------

    async def init_pool(self) -> None:
        return None

    async def close_pool(self) -> None:
        return None

    async def ping(self) -> str:
        return "mock"

    async def list_procedures(self) -> list[Procedure]:
        return [Procedure(**d) for d in self.documents.values() if d["status"] == "effective"]

    async def write_event(self, **fields: Any) -> None:
        self.events.append(fields)
        del self.events[:-1000]

    async def next_deviation_id(self) -> str:
        return f"DEV-{next(self._dev_seq):04d}"

    async def insert_deviation(self, **fields: Any) -> None:
        self.deviations.append({**fields, "ts": _now()})

    async def set_deviation_notified(self, deviation_id: str, notified: bool) -> None:
        for row in self.deviations:
            if row["deviation_id"] == deviation_id:
                row["notified"] = notified
                return
        raise LookupError(deviation_id)

    async def fail_interrupted_materials(self) -> int:
        n = 0
        for m in self.materials.values():
            if m["status"] == "converting":
                m.update(status="failed", error="Conversion interrupted by relay restart. Upload again.")
                n += 1
        return n

    # --- v2 materials + drafts ----------------------------------------------------

    async def walkthrough_citations(self, doc_id: str, revision: str) -> list[Citation]:
        return [Citation(chunk_id=c.chunk_id, doc_id=c.doc_id, revision=c.revision,
                         section=c.section, quote=c.text) for c in self.chunks
                if c.doc_id == doc_id and c.revision == revision and c.is_step]

    async def insert_material(self, filename: str, mime: str, data: bytes, doc_id: str,
                              revision: str, title: str) -> str:
        if not re.fullmatch(r"[A-Z]{2,5}-\d{3}", doc_id) or not re.fullmatch(r"[A-Z0-9]{1,3}", revision):
            raise ValueError("Invalid document or revision identifier")
        if not data or not filename or not title.strip():
            raise ValueError("Filename, title and a nonempty file are required")
        material_id = self._next("MAT")
        self.materials[material_id] = {
            "material_id": material_id, "created_at": _now(), "filename": filename, "mime": mime,
            "bytes": data, "doc_id": doc_id, "revision": revision, "title": title,
            "status": "converting", "error": None, "material_text": None}
        return material_id

    async def set_material_status(self, material_id: str, status: str, error: str | None = None) -> None:
        m = self.materials.get(material_id)
        if m is None or (m["status"] == "approved" and status != "approved"):
            raise LookupError("Material not found or already published")
        m.update(status=status, error=error)

    async def save_material_text(self, material_id: str, text: MaterialText) -> None:
        if text.material_id != material_id:
            raise ValueError("Material text belongs to a different upload")
        m = self.materials.get(material_id)
        if m is None or m["status"] == "approved":
            raise LookupError("Material not found or already published")
        m["material_text"] = text.model_dump(mode="json")

    async def get_material(self, material_id: str, *, include_bytes: bool = False) -> dict | None:
        m = self.materials.get(material_id)
        if m is None:
            return None
        return dict(m) if include_bytes else {k: v for k, v in m.items() if k != "bytes"}

    async def get_material_text(self, material_id: str) -> MaterialText | None:
        m = self.materials.get(material_id)
        return MaterialText.model_validate(m["material_text"]) if m and m["material_text"] else None

    async def list_materials(self, *, query: str = "", limit: int = 50, offset: int = 0) -> list[dict]:
        import hashlib

        needle = query.strip().lower()
        rows = [m for m in self.materials.values() if needle in " ".join(
            str(m[k]) for k in ("doc_id", "revision", "title", "filename")).lower()]
        rows.sort(key=lambda m: (m["created_at"], m["material_id"]), reverse=True)
        return [{**{k: v for k, v in m.items() if k not in ("bytes", "material_text")},
                 "size_bytes": len(m["bytes"]), "sha256": hashlib.sha256(m["bytes"]).hexdigest()}
                for m in rows[offset:offset + limit]]

    async def save_draft(self, draft: ProcedureDraft) -> None:
        m = self.materials.get(draft.material_id)
        if m is None or (m["doc_id"], m["revision"]) != (draft.doc_id, draft.revision) or m["status"] == "approved":
            raise ValueError("Material does not belong to this editable draft")
        existing = self.drafts.get((draft.doc_id, draft.revision))
        if existing and existing["approved"]:
            raise ValueError("Published revisions are immutable")
        steps = [dict(s.model_dump(mode="json"), diagram_approved=False) for s in draft.steps]
        self.drafts[(draft.doc_id, draft.revision)] = {
            "doc_id": draft.doc_id, "revision": draft.revision, "material_id": draft.material_id,
            "title": draft.title, "steps": steps, "warnings": list(draft.warnings), "approved": False}

    async def get_draft(self, doc_id: str, revision: str) -> ProcedureDraft | None:
        d = self.drafts.get((doc_id, revision))
        if d is None:
            return None
        status = "approved" if d["approved"] else self.materials[d["material_id"]]["status"]
        return ProcedureDraft(doc_id=doc_id, revision=revision, material_id=d["material_id"],
                              title=d["title"], status=status, steps=d["steps"], warnings=d["warnings"])

    def _editable(self, doc_id: str, revision: str) -> dict[str, Any]:
        d = self.drafts.get((doc_id, revision))
        if d is None:
            raise LookupError("Draft was not found")
        if d["approved"]:
            raise ValueError("Published revisions are immutable; upload a new revision")
        return d

    async def update_draft_step(self, doc_id: str, revision: str, label: str, step: DraftStep) -> None:
        if label != step.label:
            raise ValueError("Step labels cannot be renamed")
        d = self._editable(doc_id, revision)
        index = next((i for i, s in enumerate(d["steps"]) if s["label"] == label), None)
        if index is None:
            raise LookupError("Step was not found")
        value = step.model_dump(mode="json")
        previous = d["steps"][index]
        changed = any(previous.get(k) != value.get(k) for k in ("diagram", "diagram_id", "quotes"))
        if value.get("diagram_id"):
            g = self.diagrams.get(value["diagram_id"])
            if g is None or (g["doc_id"], g["revision"], g["step_label"]) != (doc_id, revision, label) \
                    or g["spec"] != value.get("diagram"):
                raise ValueError("Diagram does not match this step; regenerate or detach it")
            value["diagram_approved"] = bool(g["approved"]) and not changed
            if changed:
                g["approved"] = False
        else:
            value["diagram_approved"] = False
        d["steps"][index] = value

    async def save_diagram(self, doc_id: str, revision: str, label: str, spec: DiagramSpec,
                           tiles: list[bytes], preview: bytes) -> str:
        if not 1 <= len(tiles) <= 2 or not preview:
            raise ValueError("Diagram needs 1-2 nonempty tiles and a preview")
        diagram_id = self._next("DGM")
        self.diagrams[diagram_id] = {
            "diagram_id": diagram_id, "doc_id": doc_id, "revision": revision, "step_label": label,
            "spec": spec.model_dump(mode="json"), "tiles": list(tiles), "preview_png": preview,
            "approved": False}
        return diagram_id

    async def approve_diagram(self, diagram_id: str) -> None:
        g = self.diagrams.get(diagram_id)
        if g is None:
            raise LookupError("Diagram was not found")
        d = self._editable(g["doc_id"], g["revision"])
        step = next((s for s in d["steps"] if s.get("diagram_id") == diagram_id), None)
        if step is None or step.get("diagram") != g["spec"]:
            raise ValueError("Diagram is not attached to this draft")
        if not (step.get("verify") or {}).get("ok"):
            raise ValueError("Verify the step before approving its diagram")
        step["diagram_approved"] = True
        g["approved"] = True

    async def get_diagram(self, diagram_id: str, approved_only: bool = True) -> dict | None:
        g = self.diagrams.get(diagram_id)
        if g is None:
            return None
        if approved_only:
            doc = self.documents.get((g["doc_id"], g["revision"]))
            pinned = any(a["doc_id"] == g["doc_id"] and a["revision"] == g["revision"]
                         and a["completed_at"] is None for a in self.assignments.values())
            if not g["approved"] or not ((doc and doc["status"] == "effective") or pinned):
                return None
        return dict(g)

    async def publish_draft(self, doc_id: str, revision: str, verify_step: Any) -> dict:
        """Mock of Part 5's walkthrough.publish_draft: re-verify, then publish into the
        same chunks the lens and Q&A read, superseding the previous effective revision."""
        draft = await self.get_draft(doc_id, revision)
        if draft is None:
            raise LookupError("Draft was not found")
        if draft.status not in {"ready", "approved"} or not draft.steps:
            raise ValueError("A ready draft with at least one step is required")
        material = await self.get_material_text(draft.material_id)
        if material is None:
            raise ValueError("Source material text is missing")
        reasons = []
        for s in draft.steps:
            result = verify_step(s, material)
            if not s.verify.ok or not result.ok or not s.quotes:
                reasons.append(f"Step {s.label}: {result.reason or s.verify.reason or 'missing source quotes'}")
            if s.diagram is not None and (not s.diagram_id or not s.diagram_approved):
                reasons.append(f"Step {s.label}: diagram needs approval or detachment")
        if reasons:
            raise ValueError("\n".join(reasons))
        for (doc, _rev), d in self.documents.items():
            if doc == doc_id and d["status"] == "effective":
                d["status"] = "superseded"
        self.documents[(doc_id, revision)] = {"doc_id": doc_id, "revision": revision,
                                              "title": draft.title, "status": "effective"}
        self.chunks[:] = [c for c in self.chunks if (c.doc_id, c.revision) != (doc_id, revision)]
        for order, s in enumerate(draft.steps, 1):
            chunk_id = f"{doc_id}:{revision}:{s.label}"
            self.chunks.append(Chunk(chunk_id=chunk_id, doc_id=doc_id, revision=revision,
                                     section=s.label, heading=s.glance, text="\n".join(s.quotes),
                                     title=draft.title, is_step=True, step_order=order))
            diagram = None
            if s.diagram is not None and s.diagram_id:
                diagram = Diagram(diagram_id=s.diagram_id, width=576, height=144, alt=s.diagram.alt)
            self.step_extras[chunk_id] = {"glance": s.glance, "body": s.body, "warning": s.warning,
                                          "checkpoint": s.checkpoint, "diagram": diagram}
        for i, w in enumerate(draft.warnings, 1):
            self.chunks.append(Chunk(chunk_id=f"{doc_id}:{revision}:warning-{i}", doc_id=doc_id,
                                     revision=revision, section=f"warning-{i}", heading="Warning",
                                     text=w, title=draft.title))
        self.drafts[(doc_id, revision)]["approved"] = True
        self.materials[draft.material_id].update(status="approved", error=None)
        return {"doc_id": doc_id, "revision": revision, "steps": len(draft.steps)}

    # --- v2 devices, assignments, progress ------------------------------------------

    async def create_device(self, token_sha256: str, pair_code: str, expires: datetime) -> str:
        if not re.fullmatch(r"[0-9a-f]{64}", token_sha256):
            raise ValueError("Store a SHA-256 token hash, never the device token")
        now = _now()
        if any(d["pair_code"] == pair_code and d["claimed_at"] is None and d["pair_expires"] > now
               for d in self.devices.values()):
            raise ValueError("Pair code already in use")
        device_id = self._next("LNS")
        self.devices[device_id] = {"device_id": device_id, "token_sha256": token_sha256,
                                   "pair_code": pair_code, "pair_expires": expires,
                                   "worker_name": None, "claimed_at": None, "created_at": now}
        return device_id

    @staticmethod
    def _public(d: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in d.items() if k != "token_sha256"}

    async def claim_device(self, pair_code: str, worker_name: str) -> dict | None:
        if not worker_name.strip() or len(worker_name) > 120:
            raise ValueError("Worker name must have 1-120 characters")
        code, now = pair_code.strip().upper(), _now()
        for d in self.devices.values():
            if d["pair_code"] == code and d["claimed_at"] is None and d["pair_expires"] > now:
                d.update(worker_name=worker_name.strip(), claimed_at=now)
                return self._public(d)
        return None

    async def device_by_token(self, token_sha256: str) -> dict | None:
        d = next((d for d in self.devices.values() if d["token_sha256"] == token_sha256), None)
        return self._public(d) if d else None

    async def list_devices(self) -> list[dict]:
        return [self._public(d) for d in sorted(self.devices.values(), key=lambda d: d["created_at"])]

    async def create_assignment(self, device_id: str, doc_id: str, revision: str | None = None) -> str:
        device = self.devices.get(device_id)
        rev = revision if revision is not None else self.effective_revision(doc_id)
        doc = self.documents.get((doc_id, rev)) if rev else None
        has_steps = any(c.doc_id == doc_id and c.revision == rev and c.is_step for c in self.chunks)
        if device is None or device["claimed_at"] is None or doc is None \
                or doc["status"] not in ("effective", "superseded") or not has_steps:
            raise LookupError("Claimed device or published procedure was not found")
        assignment_id = self._next("ASN")
        self.assignments[assignment_id] = {
            "assignment_id": assignment_id, "device_id": device_id, "doc_id": doc_id,
            "revision": rev, "assigned_at": _now(), "delivered_at": None, "completed_at": None}
        return assignment_id

    async def next_assignment(self, device_id: str) -> dict | None:
        # Same rule as db.next_assignment: re-send a delivered task with no progress after 30 s.
        now = _now()
        acted = {k[0] for k in self.progress}

        def due(a: dict) -> bool:
            if a["device_id"] != device_id or a["completed_at"] is not None:
                return False
            return a["delivered_at"] is None or (
                now - a["delivered_at"] > timedelta(seconds=30) and now - a["assigned_at"] < timedelta(hours=12)
                and a["assignment_id"] not in acted)

        pending = sorted(filter(due, self.assignments.values()), key=lambda a: (a["assigned_at"], a["assignment_id"]))
        if not pending:
            return None
        pending[0]["delivered_at"] = _now()
        return dict(pending[0])

    async def insert_progress(self, events: list[ProgressEvent], *, device_id: str | None = None) -> int:
        if not device_id or len(events) > 100:
            return 0
        accepted = 0
        for e in events:
            a = self.assignments.get(e.assignment_id)
            if a is None or a["device_id"] != device_id:
                continue
            key = (e.assignment_id, e.step_id or "", e.kind, float(e.ts))
            if key in self.progress:
                continue
            self.progress[key] = {"assignment_id": e.assignment_id, "step_id": e.step_id,
                                  "kind": e.kind, "ts": float(e.ts), "received_at": _now()}
            accepted += 1
            if e.kind == "task_completed" and a["completed_at"] is None:
                a["completed_at"] = datetime.fromtimestamp(e.ts / 1000, timezone.utc)
        return accepted

    async def progress_board(self, since: float | None = None) -> list[dict]:
        rows = []
        for a in sorted(self.assignments.values(), key=lambda a: a["assigned_at"], reverse=True):
            if a["completed_at"] is not None:
                continue
            events = sorted((p for p in self.progress.values() if p["assignment_id"] == a["assignment_id"]),
                            key=lambda p: p["ts"])
            last = events[-1] if events else None
            stepped = [p for p in events if p["step_id"]]
            step_id = stepped[-1]["step_id"] if stepped else None
            order = next((c.step_order or 0 for c in self.chunks if c.chunk_id == step_id), 0)
            started = [p["ts"] for p in events if p["step_id"] == step_id and p["kind"] == "step_started"]
            changed = max([_ms(a["assigned_at"]), *[_ms(p["received_at"]) for p in events]])
            if since is not None and changed < since:
                continue
            rows.append({
                "device_id": a["device_id"], "worker_name": self.devices[a["device_id"]]["worker_name"],
                "assignment_id": a["assignment_id"], "doc_id": a["doc_id"], "revision": a["revision"],
                "title": self.documents[(a["doc_id"], a["revision"])]["title"], "step_index": order,
                "total": sum(1 for c in self.chunks if c.doc_id == a["doc_id"]
                             and c.revision == a["revision"] and c.is_step),
                "kind": last["kind"] if last else "assigned",
                "ts": last["ts"] if last else _ms(a["assigned_at"]),
                "step_started_at": started[-1] if started else (last["ts"] if last else _ms(a["assigned_at"])),
                "deviations": [{"deviation_id": v["deviation_id"], "text": v["text"], "ts": _ms(v["ts"])}
                               for v in self.deviations if v.get("doc_id") == a["doc_id"]
                               and v["ts"] >= a["assigned_at"]],
            })
        return rows


# --- v2 conversion stand-ins (Part 4 owns the real ones) -----------------------------

MOCK_BINARY_NOTE = ("MOCK EXTRACTION (MOCK_MODE=1): binary files are not read by the mock "
                    "converter; this synthetic seal-swap procedure stands in for the upload.")
MOCK_BINARY_MATERIAL = f"""{MOCK_BINARY_NOTE}

WARNING: Isolate power and drain the pump before opening the seal housing.

1. Disconnect power and close the inlet and outlet valves.
2. Remove the four gland nuts with a 10 mm socket.
3. Pull the old seal and clean the housing face with a lint-free cloth.
4. Fit the new seal with the spring side toward the impeller.
5. Torque the four gland nuts to 6 N-m in a star pattern.
6. Open the valves and run the pump for 2 min. No drip is allowed at the gland.
"""

_NUMBERED = re.compile(r"^\s*(\d+(?:\.\d+)*)[.)]\s+(.+?)\s*$")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_DIGITS = re.compile(r"\d+(?:[.,]\d+)?")


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^0-9a-z]+", " ", text.lower()).split())


def _star_spec() -> DiagramSpec:
    return DiagramSpec(kind="schematic", alt="Star pattern: upper left, lower right, upper right, lower left",
                       elements=[
                           DiagramElement(type="rect", x=110, y=18, x2=466, y2=126),
                           DiagramElement(type="callout", x=150, y=42, label="1"),
                           DiagramElement(type="callout", x=426, y=102, label="2"),
                           DiagramElement(type="callout", x=426, y=42, label="3"),
                           DiagramElement(type="callout", x=150, y=102, label="4"),
                           DiagramElement(type="arrow", x=175, y=50, x2=400, y2=95),
                       ])


DEMO_SPEC = _star_spec()


class MockConverter:
    """extract(): text and markdown are read verbatim; anything else gets the
    labelled synthetic stand-in. convert(): one step per numbered line, quoted verbatim."""

    def __init__(self) -> None:
        self.extract_calls = 0
        self.convert_calls = 0

    async def extract(self, data: bytes, mime: str, material_id: str) -> MaterialText:
        self.extract_calls += 1
        await asyncio.sleep(0)
        if mime.split(";")[0].strip() in ("text/plain", "text/markdown"):
            text = data.decode("utf-8", errors="replace")
        else:
            text = MOCK_BINARY_MATERIAL
        pages = [PageText(page=i, text=p) for i, p in enumerate(text.split("\f"), 1) if p.strip()]
        return MaterialText(material_id=material_id, pages=pages or [PageText(page=1, text="")])

    async def convert(self, text: MaterialText, doc_id: str, revision: str, title: str) -> ProcedureDraft:
        self.convert_calls += 1
        await asyncio.sleep(0)
        lines = "\n".join(p.text for p in text.pages).splitlines()
        steps, warnings = [], []
        for line in lines:
            m = _NUMBERED.match(line)
            if not m:
                if line.strip().upper().startswith("WARNING:"):
                    warnings.append(line.strip())
                continue
            label, body = m.group(1), m.group(2)
            sentences = _SENTENCE.split(body)
            first = sentences[0]
            glance = first if len(first) <= GLANCE_MAX else " ".join(first.split()[:8])
            checkpoint = next((s for s in sentences[1:] if len(s) <= CHECKPOINT_MAX
                               and re.search(r"\b(must|no|allowed|not)\b", s, re.I)), None)
            step = DraftStep(label=label, glance=glance, body=body, checkpoint=checkpoint,
                             quotes=[body], diagram=_star_spec() if "star pattern" in body.lower() else None,
                             verify=VerifyResult(ok=False))
            steps.append(step.model_copy(update={"verify": verify_step(step, text)}))
        return ProcedureDraft(doc_id=doc_id, revision=revision, title=title,
                              material_id=text.material_id, status="ready" if steps else "failed",
                              steps=steps, warnings=warnings)


def verify_step(step: DraftStep, text: MaterialText) -> VerifyResult:
    """Stand-in for Part 4's verify_step: quotes in the material, every number in the
    step text inside a quote, warning quoted, caps after sanitize, sane diagram."""
    material = _norm("\n".join(p.text for p in text.pages))
    reasons: list[str] = []
    if not step.quotes:
        reasons.append("no source quotes")
    for q in step.quotes:
        if not _norm(q) or _norm(q) not in material:
            reasons.append(f"quote not found in the material: '{q[:60]}'")
    quoted = " ".join(step.quotes)
    for field, value, cap in (("glance", step.glance, GLANCE_MAX), ("body", step.body, BODY_MAX),
                              ("warning", step.warning, WARNING_MAX),
                              ("checkpoint", step.checkpoint, CHECKPOINT_MAX)):
        if value is None:
            continue
        shown = sanitize(value)
        if field == "glance" and not shown.strip():
            reasons.append("glance is empty")
        if len(shown) > cap:
            reasons.append(f"{field} is {len(shown)} chars; the lens limit is {cap}")
        for number in _DIGITS.findall(value):
            if number not in quoted:
                reasons.append(f"{field} says {number}; no quote contains {number}")
    if step.warning and _norm(step.warning) not in _norm(quoted):
        reasons.append("warning is not quoted from the material")
    spec = step.diagram
    if spec is not None:
        if len(spec.alt) > DIAGRAM_ALT_MAX:
            reasons.append(f"diagram caption is {len(spec.alt)} chars; the limit is {DIAGRAM_ALT_MAX}")
        if len(spec.elements) > DIAGRAM_ELEMENTS_MAX:
            reasons.append(f"diagram has {len(spec.elements)} elements; the limit is {DIAGRAM_ELEMENTS_MAX}")
        if any(e.label and len(e.label) > DIAGRAM_LABEL_MAX for e in spec.elements):
            reasons.append(f"a diagram label is longer than {DIAGRAM_LABEL_MAX} chars")
        if spec.kind == "crop" and spec.figure_id not in {f.figure_id for f in text.figures}:
            reasons.append(f"figure {spec.figure_id} is not in the material")
    return VerifyResult(ok=not reasons, reason="; ".join(reasons) or None)


# --- v2 renderer stand-in: stdlib PNG, no Pillow --------------------------------------

CANVAS_W, CANVAS_H, TILE_W = 576, 144, 288
_LENS_GREEN = (0x3C, 0xFA, 0x44)
_DIGIT_GLYPHS = {  # 3x5 bitmaps, drawn at 3x scale
    "0": "111101101101111", "1": "010110010010111", "2": "111001111100111", "3": "111001111001111",
    "4": "101101111001001", "5": "111100111001111", "6": "111100111101111", "7": "111001001001001",
    "8": "111101111101111", "9": "111101111001111"}


def png_bytes(width: int, height: int, rows: list[bytes], color_type: int) -> bytes:
    """Minimal PNG writer (8-bit, filter 0). color_type 0 grey, 2 RGB, 6 RGBA."""
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))
    raw = b"".join(b"\x00" + r for r in rows)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def png_size(data: bytes) -> tuple[int, int] | None:
    if data[:8] != b"\x89PNG\r\n\x1a\n" or len(data) < 24:
        return None
    return struct.unpack(">II", data[16:24])


class _Canvas:
    def __init__(self) -> None:
        self.px = bytearray(CANVAS_W * CANVAS_H)

    def dot(self, x: int, y: int, r: int = 1) -> None:
        for yy in range(y - r + 1, y + r):
            for xx in range(x - r + 1, x + r):
                if 0 <= xx < CANVAS_W and 0 <= yy < CANVAS_H:
                    self.px[yy * CANVAS_W + xx] = 255

    def line(self, x0: int, y0: int, x1: int, y1: int) -> None:
        n = max(abs(x1 - x0), abs(y1 - y0), 1)
        for i in range(n + 1):
            self.dot(round(x0 + (x1 - x0) * i / n), round(y0 + (y1 - y0) * i / n))

    def circle(self, cx: int, cy: int, r: int) -> None:
        for i in range(max(24, 8 * r)):
            a = 2 * math.pi * i / max(24, 8 * r)
            self.dot(round(cx + r * math.cos(a)), round(cy + r * math.sin(a)))

    def digits(self, cx: int, cy: int, text: str) -> None:
        glyphs = [g for g in (_DIGIT_GLYPHS.get(ch) for ch in text) if g]
        x = cx - (len(glyphs) * 12 - 3) // 2
        for g in glyphs:
            for i, bit in enumerate(g):
                if bit == "1":
                    for dy in range(3):
                        for dx in range(3):
                            xx, yy = x + (i % 3) * 3 + dx, cy - 7 + (i // 3) * 3 + dy
                            if 0 <= xx < CANVAS_W and 0 <= yy < CANVAS_H:
                                self.px[yy * CANVAS_W + xx] = 255
            x += 12


class MockRenderer:
    """Stand-in for Part 4's DiagramRenderer. Tiles are 288x144 8-bit greyscale PNGs
    with every pixel at a lens level (level * 17; strokes at level 15): the format
    Part 2 proved through ImageRawDataUpdate in simulator 0.9.5 and Part 4 renders
    (``render.TILE_FORMAT = "png"``, BUILD-PLAN-V2 section 4)."""

    def render(self, spec: DiagramSpec, page_image: bytes | None) -> list[bytes]:
        c = _Canvas()
        if spec.kind == "crop":
            if page_image is None:
                raise ValueError("a crop diagram needs the page image")
            c.line(4, 4, CANVAS_W - 5, 4); c.line(CANVAS_W - 5, 4, CANVAS_W - 5, CANVAS_H - 5)  # noqa: E702
            c.line(CANVAS_W - 5, CANVAS_H - 5, 4, CANVAS_H - 5); c.line(4, CANVAS_H - 5, 4, 4)  # noqa: E702
            c.line(4, 4, CANVAS_W - 5, CANVAS_H - 5)
        for e in spec.elements:
            x2 = e.x2 if e.x2 is not None else e.x
            y2 = e.y2 if e.y2 is not None else e.y
            if e.type in ("line", "arrow"):
                c.line(e.x, e.y, x2, y2)
                if e.type == "arrow" and (x2, y2) != (e.x, e.y):
                    a = math.atan2(y2 - e.y, x2 - e.x)
                    for side in (-1, 1):
                        t = a + math.pi - side * math.radians(28)
                        c.line(x2, y2, round(x2 + 11 * math.cos(t)), round(y2 + 11 * math.sin(t)))
            elif e.type == "rect":
                for a0, b0, a1, b1 in ((e.x, e.y, x2, e.y), (x2, e.y, x2, y2), (x2, y2, e.x, y2), (e.x, y2, e.x, e.y)):
                    c.line(a0, b0, a1, b1)
            elif e.type in ("circle", "callout"):
                c.circle(e.x, e.y, max(15, e.r or 15) if e.type == "callout" else (e.r or 15))
            if e.label and e.type in ("callout", "text"):
                c.digits(e.x, e.y, e.label)
        tiles = []
        for slot in range(2):
            rows = [bytes(c.px[y * CANVAS_W + slot * TILE_W: y * CANVAS_W + (slot + 1) * TILE_W])
                    for y in range(CANVAS_H)]
            tiles.append(png_bytes(TILE_W, CANVAS_H, rows, 0))
        return tiles

    def preview_png(self, tiles: list[bytes]) -> bytes:
        """576x144 RGB PNG coloured like the lens. Re-renders from the tile PNGs' pixels."""
        canvas = bytearray(CANVAS_W * CANVAS_H)
        for slot, data in enumerate(tiles[:2]):
            for y, row in enumerate(_decode_grey_rows(data)):
                canvas[y * CANVAS_W + slot * TILE_W: y * CANVAS_W + (slot + 1) * TILE_W] = row[:TILE_W]
        rows = [bytes(round(v * ch / 255) for v in canvas[y * CANVAS_W:(y + 1) * CANVAS_W] for ch in _LENS_GREEN)
                for y in range(CANVAS_H)]
        return png_bytes(CANVAS_W, CANVAS_H, rows, 2)

    def page_image(self, data: bytes, mime: str, page: int) -> bytes:
        return png_bytes(1, 1, [b"\x00"], 0)  # mock: crops only need *a* page image


def _decode_grey_rows(data: bytes) -> list[bytes]:
    """Inverse of png_bytes for its own 8-bit grey output (filter 0 only)."""
    size = png_size(data)
    if size is None:
        raise ValueError("not a PNG tile")
    width, height = size
    idat, pos = b"", 8
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        if tag == b"IDAT":
            idat += data[pos + 8:pos + 8 + length]
        pos += 12 + length
    raw = zlib.decompress(idat)
    stride = width + 1
    return [raw[y * stride + 1:(y + 1) * stride] for y in range(height)]
