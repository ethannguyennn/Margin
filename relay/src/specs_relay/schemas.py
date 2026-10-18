"""The frozen contract, server side. Source of truth for Parts 3, 4 and 5.

Mirrors the README contract and Part 1's ``app/src/types.ts``. Import these
shapes; never redefine them. Any change needs agreement from Parts 1-5.

Length caps (glance 60, body 450) are enforced here with ``max_length``:
over-cap text raises ``ValidationError`` instead of being silently truncated,
because the lens truncates ugly.

Contract v2 (BUILD-PLAN-V2 section 5) is additive: every v1 field keeps its
meaning. Lens-facing v2 caps (``Step.warning`` 80, ``Step.checkpoint`` 60,
``Diagram.alt`` 80) are hard ``max_length`` too. The *draft* shapes
(``DraftStep``, ``DiagramSpec``, ``DiagramElement``) deliberately do not reject
over-cap text: a converted step that is too long must come back as a failing
step the supervisor can fix (Part 4's ``verify_step`` reports the cap), not as
an exception that loses the whole conversion. Approval requires every step to
verify, so nothing over-cap is ever published to the lens.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

GLANCE_MAX = 60
BODY_MAX = 450
# v2 caps (BUILD-PLAN-V2 section 5). Part 4's verify_step enforces them on drafts.
WARNING_MAX = 80
CHECKPOINT_MAX = 60
DIAGRAM_ALT_MAX = 80
# Generation targets for NEW text: Gemini answers (pipeline/verify.py) and newly
# converted steps (convert/verify_step.py). Tighter than the contract ceilings
# above, which still bound everything already published: the lens should carry
# as few words as possible, so a draft over these is rejected and retried.
ANSWER_GLANCE_MAX = 40
ANSWER_BODY_MAX = 200
STEP_WARNING_MAX = 50
STEP_CHECKPOINT_MAX = 40
DIAGRAM_LABEL_MAX = 12
DIAGRAM_ELEMENTS_MAX = 40
TITLE_MAX = 120

Intent = Literal["question", "walkthrough", "deviation", "repeat", "command", "unknown"]
Outcome = Literal["answered", "not_found", "logged", "clarify", "command", "error"]
Command = Literal["next", "back", "repeat", "details", "diagram", "pause", "resume", "exit"]
# `internal` and the HTTP-status codes below are relay-only additions; the app
# treats any code it does not know as a generic error (TS `error.code: string`).
ErrorCode = Literal["stt_failed", "db_down", "llm_timeout", "bad_request", "internal",
                    "unauthorized", "not_found", "conflict", "rate_limited",
                    "payload_too_large", "unsupported_media_type"]

NOT_FOUND_GLANCE = "Not in approved SOPs"
NOT_FOUND_BODY = "No matching procedure. Try rephrasing or ask your supervisor."

GlanceText = Annotated[str, Field(max_length=GLANCE_MAX)]
BodyText = Annotated[str, Field(max_length=BODY_MAX)]
WarningText = Annotated[str, Field(max_length=WARNING_MAX)]
CheckpointText = Annotated[str, Field(max_length=CHECKPOINT_MAX)]
AltText = Annotated[str, Field(max_length=DIAGRAM_ALT_MAX)]


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
    assignment_id: str | None = None  # v2: the lens is inside an assigned task


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


class Diagram(_Model):
    """An approved diagram attached to a step; the tiles come from GET /v1/diagrams/{id}."""

    diagram_id: str
    width: int
    height: int
    alt: AltText


class Step(_Model):
    step_id: str  # chunk_id of the step
    label: str  # human section number, e.g. '4.1'
    glance: GlanceText
    body: BodyText
    warning: WarningText | None = None  # v2, shown on the step screen
    checkpoint: CheckpointText | None = None  # v2, e.g. "0.20 mm gauge must not enter"
    diagram: Diagram | None = None  # v2, only approved diagrams are ever sent
    graphic_id: str | None = None  # revision-pinned synthetic reference


class Walkthrough(_Model):
    doc_id: str
    revision: str
    title: str
    total: int
    index: int = 0
    steps: list[Step]
    assignment_id: str | None = None  # v2: set when the walkthrough is an assigned task


class Latency(_Model):
    stt: int = 0
    embed: int = 0
    retrieve: int = 0
    generate: int = 0
    verify: int = 0
    total: int = 0


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
    latency_ms: Latency
    # Additive field: true only on a not_found the model judged ambiguous between
    # procedures (Part 5's eval checks it; clients that ignore it render NOT FOUND).
    needs_clarification: bool = False
    # v2: set iff outcome == 'command'. The lens acts on it and never renders text.
    command: Command | None = None
    graphic_id: str | None = None

    @model_validator(mode="after")
    def _never_unverified_answer(self) -> AskResponse:
        if self.outcome == "answered" and (not self.verified or not self.citations):
            raise ValueError("an `answered` response must be verified and carry citations")
        if self.graphic_id is not None and (self.outcome != "answered" or not self.verified):
            raise ValueError("a graphic requires a verified answer")
        if (self.outcome == "command") != (self.command is not None):
            raise ValueError("`command` is set iff outcome == 'command'")
        if self.outcome == "command" and (self.verified or self.glance or self.body or self.citations):
            raise ValueError("a `command` response carries verified=false and no glance/body/citations")
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


# --- v2 lens routes: devices, assignments, progress, diagrams -----------------

# Pair codes avoid look-alikes: no 0/O, no 1/I (matches Part 5's devices check).
PAIR_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
PAIR_CODE_PATTERN = r"^[A-HJ-NP-Za-hj-np-z2-9]{4}$"
DOC_ID_PATTERN = r"^[A-Z]{2,5}-\d{3}$"
REVISION_PATTERN = r"^[A-Z0-9]{1,3}$"

ProgressKind = Literal["task_started", "step_started", "step_completed", "task_paused", "task_completed"]


class PairRequest(_Model):
    session_id: UUID


class Pairing(_Model):
    device_id: str
    # Only ever returned to the device itself (pair, me); "" on portal responses.
    device_token: str
    pair_code: str
    claimed: bool
    worker_name: str | None = None


class DeviceInfo(_Model):
    """GET /v1/devices row: a Pairing without the token, plus timestamps."""

    device_id: str
    pair_code: str | None = None  # the open code, only while unclaimed and unexpired
    claimed: bool
    worker_name: str | None = None
    claimed_at: str | None = None  # ISO 8601
    created_at: str | None = None


class ClaimRequest(_Model):
    pair_code: str = Field(pattern=PAIR_CODE_PATTERN)
    worker_name: str = Field(min_length=1, max_length=120)


class AssignRequest(_Model):
    device_id: str = Field(min_length=1, max_length=64)
    doc_id: str = Field(pattern=DOC_ID_PATTERN)
    revision: str | None = Field(default=None, pattern=REVISION_PATTERN)


class Assignment(_Model):
    assignment_id: str
    walkthrough: Walkthrough
    assigned_at: str  # ISO 8601


class ProgressEvent(_Model):
    assignment_id: str
    step_id: str | None = None
    kind: ProgressKind
    ts: float  # Unix milliseconds; (assignment_id, step_id, kind, ts) is the idempotency key


class ProgressBatch(_Model):
    # Part 2 flushes every 5 s / 10 events but may replay up to 200 after being offline.
    events: list[ProgressEvent] = Field(max_length=500)


class ProgressAccepted(_Model):
    accepted: int


class BoardRow(BaseModel):
    """GET /v1/progress row. Part 5's query adds revision, step_started_at, deviations."""

    model_config = ConfigDict(extra="allow")

    device_id: str
    worker_name: str | None = None
    assignment_id: str
    doc_id: str
    title: str
    step_index: int
    total: int
    kind: str
    ts: float


class DiagramTile(_Model):
    slot: Literal[0, 1]
    width: int
    height: int
    image: str  # base64 of the tile bytes, in the lens format (BUILD-PLAN-V2 section 4)


class DiagramImage(_Model):
    diagram_id: str
    tiles: list[DiagramTile]


# --- v2 authoring: materials, drafts, diagram specs (Parts 4 and 5) -----------


class PageText(BaseModel):
    page: int
    text: str  # verbatim markdown of that page


class Figure(BaseModel):
    figure_id: str
    page: int
    bbox: tuple[float, float, float, float]  # normalised 0..1 within the page
    caption: str = ""


class MaterialText(BaseModel):
    """extract() output; what the supervisor reviews and every quote is checked against."""

    material_id: str
    pages: list[PageText]
    figures: list[Figure] = Field(default_factory=list)


class DiagramElement(BaseModel):
    """Schematic primitive on the 576x144 canvas. label <= DIAGRAM_LABEL_MAX (verify_step)."""

    type: Literal["line", "arrow", "rect", "circle", "text", "callout"]
    x: int
    y: int
    x2: int | None = None
    y2: int | None = None
    r: int | None = None
    label: str | None = None


class DiagramSpec(BaseModel):
    kind: Literal["crop", "schematic"]
    figure_id: str | None = None  # crop
    bbox: tuple[float, float, float, float] | None = None  # crop, within the figure's page
    elements: list[DiagramElement] = Field(default_factory=list)  # schematic, <= 40
    alt: str  # <= DIAGRAM_ALT_MAX, also the lens caption


class DraftStep(BaseModel):
    label: str
    glance: str  # same caps as v1 Step, enforced by verify_step
    body: str
    warning: str | None = None
    checkpoint: str | None = None
    quotes: list[str] = Field(default_factory=list)  # verbatim from MaterialText
    diagram: DiagramSpec | None = None
    diagram_id: str | None = None  # set after render
    diagram_approved: bool = False
    verify: VerifyResult


class ProcedureDraft(BaseModel):
    doc_id: str
    revision: str
    title: str
    material_id: str
    status: Literal["converting", "ready", "failed", "approved"]
    steps: list[DraftStep]
    warnings: list[str] = Field(default_factory=list)  # document-level, one chunk each


class DraftStepEdit(_Model):
    """PUT /v1/drafts/{doc}/{rev}/steps/{label}. Only the fields sent are changed;
    ``diagram: null`` (with ``diagram_id: null``) detaches the diagram."""

    glance: str | None = None
    body: str | None = None
    warning: str | None = None
    checkpoint: str | None = None
    quotes: list[str] | None = None
    diagram: DiagramSpec | None = None
    diagram_id: str | None = None


class MaterialCreated(_Model):
    material_id: str
    status: Literal["converting"] = "converting"


class MaterialStatus(_Model):
    material_id: str
    status: Literal["converting", "ready", "failed", "approved"]
    error: str | None = None
    doc_id: str
    revision: str
    title: str | None = None
    filename: str | None = None


class ApproveResult(_Model):
    doc_id: str
    revision: str
    steps: list[Step]  # the published steps, as the lens will receive them


class OkResponse(_Model):
    ok: bool = True
