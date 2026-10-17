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
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import re
from typing import Any

from .. import obs
from ..schemas import (
    BODY_MAX,
    GLANCE_MAX,
    Chunk,
    Citation,
    Draft,
    DraftCitation,
    Intent,
    IntentResult,
    Procedure,
    RetrievalResult,
    Step,
    VerifyResult,
)
from . import LlmTimeout

log = logging.getLogger("margin.mock")

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
    (re.compile(r"how tight|torque|\bm5\b|bracket|mounting|guide me|walk me through"),
     ["SOP-114:C:4.2", "SOP-114:C:4.1"]),
]

# --- intent / sanitize (stand-ins until Part 4's real modules land) ----------

_INTENT_RULES: list[tuple[Intent, re.Pattern[str]]] = [
    ("walkthrough", re.compile(r"guide me|walk me through|step by step|take me through|start procedure", re.I)),
    ("deviation", re.compile(r"log (a )?deviation|report (an )?(issue|problem|nonconformance)|flag this", re.I)),
    ("repeat", re.compile(r"\brepeat\b|say that again|^\s*what was that\s*\??\s*$", re.I)),
]


def classify_intent(transcript: str) -> IntentResult:
    if not transcript.strip():
        return IntentResult(intent="unknown", text="")
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
    def __init__(self, chunks: list[Chunk] | None = None) -> None:
        self.chunks = chunks if chunks is not None else MOCK_CHUNKS
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
        steps = [c for c in self.chunks if c.doc_id == doc_id and c.is_step
                 and (revision is None or c.revision == revision)]
        steps.sort(key=lambda c: c.step_order or 0)
        return [Step(step_id=c.chunk_id, label=c.section,
                     glance=_fit(f"{c.section} {c.heading or ''}".strip(), GLANCE_MAX),
                     body=_fit(c.text, BODY_MAX)) for c in steps]


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
        used = [top]
        body = top.text
        for extra in chunks[1:]:
            if extra.doc_id == top.doc_id and len(body) + 1 + len(extra.text) <= BODY_MAX:
                body = f"{body} {extra.text}"
                used.append(extra)
        if top.chunk_id == "SOP-114:C:4.2":
            glance = "Step 4.2: torque M5 to 4 N-m"
        else:
            glance = f"Sec {top.section}: {top.heading or top.doc_id}"[:GLANCE_MAX]
        return Draft(answerable=True, glance=glance, body=body,
                     citations=[DraftCitation(chunk_id=c.chunk_id, quote=c.text) for c in used])


class MockNotifier:
    async def notify(self, deviation_id: str, text: str) -> bool:
        log.info("MOCK notify supervisor: %s", deviation_id)
        return True


class MockDB:
    """In-memory stand-in for Part 5's db module (same function names)."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.deviations: list[dict[str, Any]] = []
        self._dev_seq = itertools.count(1)

    async def init_pool(self) -> None:
        return None

    async def close_pool(self) -> None:
        return None

    async def ping(self) -> str:
        return "mock"

    async def list_procedures(self) -> list[Procedure]:
        seen: dict[tuple[str, str], Procedure] = {}
        for c in MOCK_CHUNKS:
            seen.setdefault((c.doc_id, c.revision), Procedure(
                doc_id=c.doc_id, title=c.title or c.doc_id, revision=c.revision, status="effective"))
        return list(seen.values())

    async def write_event(self, **fields: Any) -> None:
        self.events.append(fields)
        del self.events[:-1000]

    async def next_deviation_id(self) -> str:
        return f"DEV-{next(self._dev_seq):04d}"

    async def insert_deviation(self, **fields: Any) -> None:
        self.deviations.append(fields)
