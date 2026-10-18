"""POST /v1/ask -- the one place the request flow lives.

transcript -> parse_command (v2: whole-utterance command -> outcome 'command', no
              retrieval, no LLM; "repeat" counts only inside a task)
-> intent -> branch:
  deviation   -> store + notify                       -> logged
  repeat      -> session's last answer, no pipeline
  walkthrough -> retrieve -> top chunk's doc -> every step at once
  question    -> retrieve -> gate (not_found, no LLM) -> generate -> verify
                 -> fail: generate once more with the reason -> verify -> fail: not_found
-> sanitize -> source -> one events row.

Unverified text is never returned as an answer. Every response carries trace_id.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import inspect
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import sentry_sdk
from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .. import obs
from ..main import Pipeline, error_response, trace_id_of
from ..pipeline import PipelineError
from ..schemas import (
    BODY_MAX,
    GLANCE_MAX,
    NOT_FOUND_BODY,
    NOT_FOUND_GLANCE,
    AskRequest,
    AskResponse,
    Chunk,
    Citation,
    Intent,
    Outcome,
    RetrievalResult,
)
from .common import load_walkthrough
from .deviation import log_deviation

log = logging.getLogger("specs.ask")

# A second Gemini attempt is only started with at least this much budget left; less
# than that and it would just be cancelled, and the lens would wait for nothing.
MIN_ATTEMPT_S = 1.0
# Pause before retrying after a 429 / 5xx from Gemini.
TRANSIENT_BACKOFF_S = 0.4
router = APIRouter()

CODES = {"stt_failed", "db_down", "llm_timeout", "bad_request", "internal"}
BYTES_PER_SAMPLE = 2  # pcm_s16le, mono


class Fail(Exception):
    """A contract error: `/v1/ask` answers with {trace_id, outcome: error, error}."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def _fail_from(exc: BaseException, default: str, what: str) -> Fail:
    """Typed errors carry `.code` (Part 3's PipelineError, Part 4's EmbeddingError,
    RetrievalError, GenerationError); anything else maps to the stage's default."""
    if isinstance(exc, Fail):
        return exc
    code = getattr(exc, "code", None)
    if code not in CODES:
        code = default
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return Fail(code, f"{what} timed out")
    detail = exc.message if isinstance(exc, PipelineError) else type(exc).__name__
    return Fail(code, f"{what} failed: {detail}")


@dataclass
class _Ctx:
    """What the events row needs, filled in as the request progresses."""

    transcript: str = ""
    intent: Intent = "unknown"
    outcome: Outcome = "error"
    doc_ids: list[str] = field(default_factory=list)


def _source(c: Citation) -> str:
    return f"{c.doc_id} Sec {c.section} rev {c.revision}"


def _source_from_step_id(step_id: str | None, doc_id: str | None) -> str:
    parts = (step_id or "").split(":")
    if len(parts) == 3 and all(parts):
        return f"{parts[0]} Sec {parts[2]} rev {parts[1]}"
    return doc_id or ""


# --- stages ---------------------------------------------------------------------------


async def _transcript(req: AskRequest, p: Pipeline, settings: Any) -> str:
    if req.text is not None and req.text.strip():
        return req.text.strip()
    assert req.audio is not None  # schema guarantees exactly one input
    try:
        pcm = base64.b64decode(req.audio.data_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise Fail("bad_request", "audio.data_b64 is not valid base64") from exc
    if not pcm or len(pcm) % BYTES_PER_SAMPLE:
        raise Fail("bad_request", "audio must be non-empty 16-bit PCM")
    seconds = len(pcm) / (BYTES_PER_SAMPLE * req.audio.sample_rate * req.audio.channels)
    if seconds > settings.max_audio_seconds:
        raise Fail("bad_request",
                   f"audio is {seconds:.1f} s; the limit is {settings.max_audio_seconds:g} s")
    try:
        with obs.stage("stt"):
            text = await asyncio.wait_for(p.transcriber.transcribe(pcm, req.audio.sample_rate),
                                          timeout=settings.stt_timeout_s)
    except Exception as exc:
        raise _fail_from(exc, "stt_failed", "transcription") from exc
    finally:
        del pcm  # in memory only, dropped as soon as STT is done
    return (text or "").strip()


async def _retrieve(p: Pipeline, query: str, revision: str | None) -> RetrievalResult:
    try:
        embedding = None
        if hasattr(p.retriever, "embed"):
            with obs.stage("embed"):
                embedding = await p.retriever.embed(query)
        with obs.stage("retrieve"):
            if embedding is not None:
                return await p.retriever.retrieve(query, revision, q_embedding=embedding)
            return await p.retriever.retrieve(query, revision)
    except Exception as exc:
        raise _fail_from(exc, "db_down", "retrieval") from exc


async def _current_step(p: Pipeline, req: AskRequest) -> Chunk | None:
    """The step the worker is on, as a citable chunk, so "how long do I do that for?"
    resolves against it. Same text the lens shows; None when it can't be loaded."""
    doc_id, step_id = req.context.doc_id, req.context.step_id
    if not doc_id or not step_id:
        return None
    try:
        walk = await load_walkthrough(p, doc_id, req.revision or None)
    except Exception as exc:  # noqa: BLE001 -- a follow-up still works on plain retrieval
        log.info("step context unavailable: %s", type(exc).__name__)
        return None
    step = next((s for s in walk.steps if s.step_id == step_id), None) if walk else None
    if step is None:
        return None
    return Chunk(chunk_id=step.step_id, doc_id=walk.doc_id, revision=walk.revision, section=step.label,
                 heading=step.glance, is_step=True,
                 text="\n".join(t for t in (step.body, step.warning, step.checkpoint) if t))


def _gate_refuses(p: Pipeline, r: RetrievalResult) -> bool:
    """not_found without calling the LLM: nothing retrieved, or both signals weak."""
    return not r.chunks or (r.best_sim < p.min_sim and r.best_rrf < p.min_rrf)


def _is_timeout(exc: BaseException) -> bool:
    return isinstance(exc, (asyncio.TimeoutError, TimeoutError)) or "Timeout" in type(exc).__name__


CLARIFY = "clarify"  # _answer's marker: the model found the question ambiguous


async def _answer(p: Pipeline, settings: Any, query: str, r: RetrievalResult,
                  deadline: float | None = None
                  ) -> tuple[str, str, list[Citation], str | None] | str | None:
    """generate -> verify, retried once with the failure reason. None means not_found,
    CLARIFY means not_found with needs_clarification.

    ``deadline`` (time.monotonic()) is the end of the ask budget: each attempt is capped
    by what is left, and the retry is skipped when too little remains to finish it."""
    feedback: str | None = None
    last_exc: BaseException | None = None
    transient = False
    for _attempt in range(2):
        timeout = settings.generate_timeout_s
        if deadline is not None:
            left = deadline - time.monotonic()
            if _attempt and left < MIN_ATTEMPT_S + (TRANSIENT_BACKOFF_S if transient else 0):
                log.info("skipping generation retry: %.1f s of the ask budget left", left)
                break
            timeout = min(timeout, max(left, MIN_ATTEMPT_S))
        if transient:
            await asyncio.sleep(TRANSIENT_BACKOFF_S)
        try:
            with obs.stage("generate"):
                draft = await asyncio.wait_for(
                    p.generator.generate(query, r.chunks, feedback=feedback),
                    timeout=timeout)
        except Exception as exc:
            if _is_timeout(exc):
                raise _fail_from(exc, "llm_timeout", "generation") from exc
            last_exc = exc
            transient = bool(getattr(exc, "transient", False))
            if not transient:  # malformed output / API error: one retry, like a verify failure
                feedback = f"malformed_output: {type(exc).__name__}. Return JSON matching the schema."
            continue
        transient = False
        last_exc = None
        if draft.needs_clarification:
            return CLARIFY
        if not draft.answerable:
            return None  # the model refusing is a success state, not something to retry
        with obs.stage("verify"):
            result = p.verify(draft, r.chunks)
        if result.ok and result.citations:
            glance = p.sanitize(draft.glance).strip()
            body = p.sanitize(draft.body).strip()
            return glance, body, list(result.citations), draft.graphic_id
        feedback = result.reason or "verification failed"
        log.info("verify failed (attempt %d): %s", _attempt + 1, feedback.split(":")[0])
    if last_exc is not None:
        raise _fail_from(last_exc, "llm_timeout", "generation") from last_exc
    return None


# --- the route ------------------------------------------------------------------------


def _response(trace_id: str, ctx: _Ctx, timer: obs.StageTimer, **kw: Any) -> AskResponse:
    defaults: dict[str, Any] = dict(glance=NOT_FOUND_GLANCE, body=NOT_FOUND_BODY, source="",
                                    citations=[], verified=False, walkthrough=None)
    defaults.update(kw)
    return AskResponse(trace_id=trace_id, transcript=ctx.transcript, intent=ctx.intent,
                       outcome=ctx.outcome, latency_ms=timer.latency(), **defaults)


async def _run(req: AskRequest, p: Pipeline, settings: Any, trace_id: str, ctx: _Ctx,
               timer: obs.StageTimer) -> AskResponse:
    session_id = str(req.session_id)
    deadline = time.monotonic() + settings.ask_budget_s
    ctx.transcript = await _transcript(req, p, settings)

    # v2 command fast path (README-PART-3 section 4): whole-utterance commands return
    # immediately -- no retrieval, no LLM, one events row. "repeat" is a command only
    # inside a task (context has step_id); outside one it keeps v1's replay below.
    command = p.parse_command(ctx.transcript) if ctx.transcript else None
    if command == "repeat" and not req.context.step_id:
        command = None
    if command:
        ctx.intent = ctx.outcome = "command"
        ctx.doc_ids = [req.context.doc_id] if req.context.doc_id else []
        return _response(trace_id, ctx, timer, glance="", body="", source="", citations=[],
                         verified=False, command=command)

    classified = p.classify(ctx.transcript)
    ctx.intent = classified.intent
    if ctx.intent == "command":
        # The classifier matched a command the fast path declined ("repeat" outside a task).
        ctx.intent = "repeat" if p.parse_command(ctx.transcript) == "repeat" else "question"

    if ctx.intent == "unknown":
        ctx.outcome = "not_found"
        return _response(trace_id, ctx, timer)

    if ctx.intent == "repeat":
        last: AskResponse | None = p.sessions.get(session_id)
        if last is None:
            ctx.outcome = "not_found"
            return _response(trace_id, ctx, timer)
        ctx.outcome = last.outcome
        ctx.doc_ids = sorted({c.doc_id for c in last.citations})
        return last.model_copy(update={"trace_id": trace_id, "transcript": ctx.transcript,
                                       "intent": "repeat", "latency_ms": timer.latency()})

    if ctx.intent == "deviation":
        text = (classified.text or ctx.transcript).strip() or ctx.transcript
        doc_id, step_id = req.context.doc_id, req.context.step_id
        try:
            dev = await log_deviation(p, session_id=session_id, text=text, doc_id=doc_id,
                                      step_id=step_id)
        except PipelineError as exc:
            raise Fail(exc.code, exc.message) from exc
        ctx.outcome = "logged"
        ctx.doc_ids = [doc_id] if doc_id else []
        source = _source_from_step_id(step_id, doc_id)
        against = f" against {source}" if source else ""
        # "Alert sent" only: a console notifier is delivery, not a human acknowledging it.
        tail = ("Supervisor alert sent." if dev.notified
                else "Supervisor alert failed; tell your supervisor directly.")
        return _response(trace_id, ctx, timer, glance=f"Deviation {dev.deviation_id} logged",
                         body=f"Deviation {dev.deviation_id} recorded{against}. {tail}",
                         source=source)

    revision = req.revision or None
    retrieved = await _retrieve(p, ctx.transcript, revision)
    here = await _current_step(p, req) if ctx.intent == "question" else None
    query = ctx.transcript
    if here is not None:
        others = [c for c in retrieved.chunks if c.chunk_id != here.chunk_id]
        retrieved = retrieved.model_copy(update={"chunks": [here, *others][:6]})
        query = (f"{ctx.transcript}\n(The worker is on step {here.section} of {here.doc_id}, "
                 f"chunk_id {here.chunk_id}. \"it\", \"that\" and \"this\" mean this step.)")
    elif _gate_refuses(p, retrieved):
        ctx.outcome = "not_found"
        return _response(trace_id, ctx, timer)

    if ctx.intent == "walkthrough":
        top = retrieved.chunks[0]
        try:
            # The one walkthrough code path (also /v1/assignments/next): keeps the v2
            # warning, checkpoint and approved diagram on every step.
            walk = await load_walkthrough(p, top.doc_id, revision or top.revision,
                                          title_hint=top.title)
        except PipelineError as exc:
            raise Fail(exc.code, exc.message) from exc
        if walk is None:
            ctx.outcome = "not_found"
            return _response(trace_id, ctx, timer)
        citations = [Citation(chunk_id=s.step_id, doc_id=walk.doc_id, revision=walk.revision,
                              section=s.label, quote=s.body) for s in walk.steps]
        n = walk.total
        glance = f"{walk.title}, {n} steps"
        if len(glance) > GLANCE_MAX:
            glance = f"{walk.doc_id}, {n} steps"
        ctx.outcome = "answered"
        ctx.doc_ids = [walk.doc_id]
        return _response(trace_id, ctx, timer, glance=glance,
                         body=f"{walk.title}, {n} steps. Swipe to advance."[:BODY_MAX],
                         source=_source(citations[0]), citations=citations, verified=True,
                         walkthrough=walk)

    # question
    answer = await _answer(p, settings, query, retrieved, deadline)
    if answer is None or answer == CLARIFY:
        ctx.outcome = "not_found"
        return _response(trace_id, ctx, timer, needs_clarification=answer == CLARIFY)
    glance, body, citations, graphic_id = answer
    ctx.outcome = "answered"
    ctx.doc_ids = sorted({c.doc_id for c in citations})
    return _response(trace_id, ctx, timer, glance=glance, body=body,
                     source=_source(citations[0]), citations=citations, verified=True, graphic_id=graphic_id)


def _accepts(fn: Any, name: str) -> bool:
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(prm.name == name or prm.kind is inspect.Parameter.VAR_KEYWORD for prm in params)


@router.post("/v1/ask", response_model=AskResponse)
async def ask(req: AskRequest, request: Request, background: BackgroundTasks) -> Any:
    timer = obs.start_timer()
    p: Pipeline = request.app.state.pipeline
    settings = request.app.state.settings
    trace_id = trace_id_of(request)
    ctx = _Ctx()
    sentry_sdk.set_tag("session_id", str(req.session_id))
    response: AskResponse | JSONResponse
    try:
        result = await _run(req, p, settings, trace_id, ctx, timer)
        if result.outcome == "answered" and ctx.intent != "repeat":
            p.remember(str(req.session_id), result)
        response = result
    except Fail as f:
        ctx.outcome = "error"
        log.warning("ask failed: %s (%s)", f.code, f.message)
        response = error_response(trace_id, f.code, f.message)
    except ValidationError as exc:
        # Over-cap glance/body (or another contract violation) raises loudly: never truncate.
        ctx.outcome = "error"
        sentry_sdk.capture_exception(exc)
        log.error("response violated the contract: %s",
                  "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()))
        response = error_response(trace_id, "internal", "response violated the contract")
    latency = timer.latency()
    sentry_sdk.set_tag("outcome", ctx.outcome)
    log.info("ask intent=%s outcome=%s total=%dms", ctx.intent, ctx.outcome, latency.total)
    # v2: the task context goes on the events row once Part 5's writer takes it.
    extra = ({"assignment_id": req.context.assignment_id}
             if req.context.assignment_id and _accepts(p.db.write_event, "assignment_id") else {})
    background.add_task(obs.write_event, p.db, session_id=str(req.session_id), trace_id=trace_id,
                        intent=ctx.intent, outcome=ctx.outcome, doc_ids=ctx.doc_ids,
                        transcript=ctx.transcript, latency_ms=latency.model_dump(), **extra)
    if isinstance(response, JSONResponse):
        response.background = background
    return response
