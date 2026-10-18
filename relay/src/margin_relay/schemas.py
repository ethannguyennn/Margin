"""The frozen contract, server side. Source of truth for Parts 3, 4 and 5.

Mirrors the README contract and Part 1's ``app/src/types.ts``. Import these
shapes; never redefine them. Any change needs agreement from Parts 1-5.

Length caps (glance 60, body 450) are enforced here with ``max_length``:
over-cap text raises ``ValidationError`` instead of being silently truncated,
because the lens truncates ugly.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

GLANCE_MAX = 60
BODY_MAX = 450

Intent = Literal["question", "walkthrough", "deviation", "repeat", "unknown"]
Outcome = Literal["answered", "not_found", "logged", "clarify", "error"]
# `internal` is relay-only (unexpected failure, e.g. an over-cap answer); the app
# treats any code it does not know as a generic error.
ErrorCode = Literal["stt_failed", "db_down", "llm_timeout", "bad_request", "internal"]

NOT_FOUND_GLANCE = "Not in approved SOPs"
NOT_FOUND_BODY = "No matching procedure. Try rephrasing or ask your supervisor."

GlanceText = Annotated[str, Field(max_length=GLANCE_MAX)]
BodyText = Annotated[str, Field(max_length=BODY_MAX)]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- /v1/ask request ---------------------------------------------------------


class AudioIn(_Model):
    format: Literal["pcm_s16le"]
    sample_rate: Literal[16000]
    channels: Literal[1]
    data_b64: str = Field(min_length=1)


class AskContext(_Model):
    doc_id: str | None = None
    step_id: str | None = None


class AskRequest(_Model):
    session_id: UUID
    audio: AudioIn | None = None
    text: str | None = None
    revision: str | None = None
    context: AskContext = Field(default_factory=AskContext)

    @model_validator(mode="after")
    def _exactly_one_input(self) -> AskRequest:
        has_text = self.text is not None and self.text.strip() != ""
        if has_text == (self.audio is not None):
            raise ValueError("exactly one of `audio` or `text` must be present")
        return self


# --- /v1/ask response --------------------------------------------------------


class Citation(_Model):
    chunk_id: str  # '{doc_id}:{revision}:{section}'
    doc_id: str
    revision: str
    section: str
    quote: str


class Step(_Model):
    step_id: str  # chunk_id of the step
    label: str  # human section number, e.g. '4.1'
    glance: GlanceText
    body: BodyText
    graphic_id: str | None = None


class Walkthrough(_Model):
    doc_id: str
    revision: str
    title: str
    total: int
    index: int = 0
    steps: list[Step]


class Latency(_Model):
    stt: int = 0
    embed: int = 0
    retrieve: int = 0
    generate: int = 0
    verify: int = 0
    total: int = 0


class DisplaySpec(_Model):
    kind: Literal["answer", "checklist", "warning"]
    items: list[Annotated[str, Field(min_length=1, max_length=180)]] = Field(
        min_length=1, max_length=4)


class AskResponse(_Model):
    trace_id: str
    transcript: str
    intent: Intent
    outcome: Outcome
    glance: GlanceText
    body: BodyText
    source: str
    citations: list[Citation]
    verified: bool
    walkthrough: Walkthrough | None = None
    display: DisplaySpec | None = None
    graphic_id: str | None = None
    latency_ms: Latency
    # Additive field: true only on a not_found the model judged ambiguous between
    # procedures (Part 5's eval checks it; clients that ignore it render NOT FOUND).
    needs_clarification: bool = False

    @model_validator(mode="after")
    def _never_unverified_answer(self) -> AskResponse:
        if self.outcome == "answered" and (not self.verified or not self.citations):
            raise ValueError("an `answered` response must be verified and carry citations")
        if self.display is not None and (self.outcome != "answered" or not self.verified):
            raise ValueError("generated displays require a verified answer")
        if self.graphic_id is not None and (self.outcome != "answered" or not self.verified):
            raise ValueError("visual references require a verified answer")
        return self


class ErrorBody(_Model):
    code: ErrorCode
    message: str


class ErrorResponse(_Model):
    trace_id: str
    outcome: Literal["error"] = "error"
    error: ErrorBody


# --- other routes ------------------------------------------------------------


class HealthResponse(_Model):
    ok: bool
    mock: bool
    db: str  # 'ok' | 'down' | 'mock'
    version: str


class DeviationRequest(_Model):
    session_id: UUID
    text: str = Field(min_length=1, max_length=2000)
    doc_id: str | None = None
    step_id: str | None = None
    # Accepted too: Part 2's client nests the ids as {context: {doc_id, step_id}}.
    context: AskContext | None = None


class DeviationResponse(_Model):
    deviation_id: str
    notified: bool


class Procedure(_Model):
    doc_id: str
    title: str
    revision: str
    status: Literal["effective", "superseded", "draft"]


# --- pipeline shapes (Part 4 / Part 5 produce, Part 3 consumes) --------------


class Chunk(BaseModel):
    """One retrieved chunk. `sim` / `rrf` are filled by retrieval when known."""

    model_config = ConfigDict(extra="ignore")

    chunk_id: str
    doc_id: str
    revision: str
    section: str
    text: str
    heading: str | None = None
    title: str | None = None  # document title, when the query joins it in
    is_step: bool = False
    step_order: int | None = None
    sim: float | None = None
    rrf: float | None = None


class RetrievalResult(BaseModel):
    chunks: list[Chunk]  # RRF-ordered, best first, at most 6
    best_sim: float  # best cosine similarity from the vector leg
    best_rrf: float  # best fused RRF score


class DraftCitation(BaseModel):
    chunk_id: str
    quote: str


class Draft(BaseModel):
    """Raw generator output. No caps here: verify + sanitize run before the caps bite."""

    answerable: bool
    needs_clarification: bool = False
    glance: str = ""
    body: str = ""
    citations: list[DraftCitation] = Field(default_factory=list)
    display: DisplaySpec | None = None
    graphic_id: str | None = None


class VerifyResult(BaseModel):
    ok: bool
    reason: str | None = None
    citations: list[Citation] = Field(default_factory=list)  # resolved, on pass


class IntentResult(BaseModel):
    """Optional richer return from classify_intent: `text` is the transcript with the
    trigger phrase stripped (what gets logged for a deviation)."""

    intent: Intent
    text: str
