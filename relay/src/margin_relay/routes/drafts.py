"""Draft review and approval (portal). README-PART-3 section 6.

    GET  /v1/drafts/{doc_id}/{revision}                                -> ProcedureDraft
    PUT  /v1/drafts/{doc_id}/{revision}/steps/{label}  DraftStepEdit   -> DraftStep (re-verified)
    POST /v1/drafts/{doc_id}/{revision}/diagrams/{diagram_id}/approve  -> {ok}
    POST /v1/drafts/{doc_id}/{revision}/approve                        -> {doc_id, revision, steps}

Nothing reaches the lens unless it is quoted, verified and approved by a human:
every save re-runs the deterministic ``verify_step``, and approve is refused with
409 (per-step reasons in ``detail``) unless every step verifies and every
attached diagram is approved or detached. Then Part 5's ``publish_draft``
re-verifies once more and publishes into the tables the lens and Q&A read.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, Request

from ..auth import portal_auth, require_portal
from ..schemas import ApproveResult, DraftStep, DraftStepEdit, OkResponse, ProcedureDraft
from .common import Conflict, Internal, NotFound, guarded, load_walkthrough

log = logging.getLogger("margin.drafts")
router = APIRouter()

_REASON_LINE = re.compile(r"^Step (\S+?): (.+)$")


async def _draft(p: Any, doc_id: str, revision: str) -> ProcedureDraft:
    draft = await guarded(p.db.get_draft(doc_id, revision), "loading the draft")
    if draft is None:
        raise NotFound(f"No draft for {doc_id} rev {revision}.")
    return draft


def _step(draft: ProcedureDraft, label: str) -> DraftStep:
    step = next((s for s in draft.steps if s.label == label), None)
    if step is None:
        raise NotFound(f"Step {label} is not in this draft.")
    return step


def _reasons(text: str) -> list[dict[str, str | None]]:
    out = []
    for line in filter(None, (s.strip() for s in text.splitlines())):
        m = _REASON_LINE.match(line)
        out.append({"label": m.group(1), "reason": m.group(2)} if m else {"label": None, "reason": line})
    return out


@router.get("/v1/drafts/{doc_id}/{revision}", response_model=ProcedureDraft,
             dependencies=[Depends(portal_auth)])
async def get_draft(doc_id: str, revision: str, request: Request) -> ProcedureDraft:
    require_portal(request)
    return await _draft(request.app.state.pipeline, doc_id, revision)


@router.put("/v1/drafts/{doc_id}/{revision}/steps/{label}", response_model=DraftStep,
             dependencies=[Depends(portal_auth)])
async def edit_step(doc_id: str, revision: str, label: str, edit: DraftStepEdit,
                    request: Request) -> DraftStep:
    require_portal(request)
    p = request.app.state.pipeline
    draft = await _draft(p, doc_id, revision)
    if draft.status == "approved":
        raise Conflict("Published revisions are immutable; upload a new revision.")
    step = _step(draft, label)
    sent = edit.model_fields_set
    updates: dict[str, Any] = {}
    for name in ("glance", "body"):
        if name in sent:
            updates[name] = (getattr(edit, name) or "").strip()
    for name in ("warning", "checkpoint"):
        if name in sent:
            updates[name] = (getattr(edit, name) or "").strip() or None
    if "quotes" in sent and edit.quotes is not None:
        updates["quotes"] = [q for q in (s.strip() for s in edit.quotes) if q]
    detach = ("diagram" in sent and edit.diagram is None) or ("diagram_id" in sent and edit.diagram_id is None
                                                               and "diagram" not in sent)
    respec = "diagram" in sent and edit.diagram is not None and edit.diagram != step.diagram
    if detach:
        updates.update(diagram=None, diagram_id=None, diagram_approved=False)
    material = await guarded(p.db.get_material_text(draft.material_id), "loading the material text")
    if material is None:
        raise Conflict("The source material text is missing; upload the material again.")
    new = step.model_copy(update=updates)
    if respec:
        new = await _rerender(p, draft, new.model_copy(update={"diagram": edit.diagram}), material)
    new = new.model_copy(update={"verify": p.verify_step(new, material)})
    try:
        await guarded(p.db.update_draft_step(doc_id, revision, label, new), "saving the step")
    except LookupError as exc:
        raise NotFound(str(exc)) from exc
    except ValueError as exc:
        raise Conflict(str(exc)) from exc
    return _step(await _draft(p, doc_id, revision), label)


async def _rerender(p: Any, draft: ProcedureDraft, step: DraftStep, material: Any) -> DraftStep:
    """A changed diagram spec gets new tiles + preview and a new (unapproved) diagram_id."""
    spec = step.diagram
    page_png = None
    if spec.kind == "crop":
        figure = next((f for f in material.figures if f.figure_id == spec.figure_id), None)
        row = await guarded(p.db.get_material(draft.material_id, include_bytes=True), "loading the material")
        if figure is None or row is None:
            raise Conflict(f"Figure {spec.figure_id} is not in the source material.")
        page_png = await asyncio.to_thread(p.renderer.page_image, bytes(row["bytes"]), row["mime"], figure.page)
    try:
        tiles = await asyncio.to_thread(p.renderer.render, spec, page_png)
        preview = await asyncio.to_thread(p.renderer.preview_png, tiles)
    except Exception as exc:  # noqa: BLE001
        raise Conflict(f"The diagram could not be rendered: {str(exc)[:120] or type(exc).__name__}") from exc
    diagram_id = await guarded(p.db.save_diagram(draft.doc_id, draft.revision, step.label, spec, tiles, preview),
                               "saving the diagram")
    return step.model_copy(update={"diagram_id": diagram_id, "diagram_approved": False})


@router.post("/v1/drafts/{doc_id}/{revision}/diagrams/{diagram_id}/approve", response_model=OkResponse,
             dependencies=[Depends(portal_auth)])
async def approve_diagram(doc_id: str, revision: str, diagram_id: str, request: Request) -> OkResponse:
    require_portal(request)
    p = request.app.state.pipeline
    row = await guarded(p.db.get_diagram(diagram_id, approved_only=False), "loading the diagram")
    if row is None or (row["doc_id"], row["revision"]) != (doc_id, revision):
        raise NotFound("That diagram is not part of this draft.")
    try:
        await guarded(p.db.approve_diagram(diagram_id), "approving the diagram")
    except LookupError as exc:
        raise NotFound(str(exc)) from exc
    except ValueError as exc:
        raise Conflict(str(exc)) from exc
    log.info("diagram %s approved for %s rev %s", diagram_id, doc_id, revision)
    return OkResponse()


@router.post("/v1/drafts/{doc_id}/{revision}/approve", response_model=ApproveResult,
             dependencies=[Depends(portal_auth)])
async def approve(doc_id: str, revision: str, request: Request) -> ApproveResult:
    require_portal(request)
    p = request.app.state.pipeline
    draft = await _draft(p, doc_id, revision)
    if draft.status not in ("ready", "approved"):
        raise Conflict(f"The draft is {draft.status}; only a ready draft can be approved.")
    failing = []
    for s in draft.steps:
        if not s.verify.ok:
            failing.append({"label": s.label, "reason": s.verify.reason or "fails verification"})
        if s.diagram is not None and not (s.diagram_id and s.diagram_approved):
            failing.append({"label": s.label, "reason": "diagram needs approval or detachment"})
    if not draft.steps:
        failing.append({"label": None, "reason": "the draft has no steps"})
    if failing:
        raise Conflict(f"Approval refused: {len(failing)} problem(s) to fix first.", detail=failing)
    if p.publisher is None:
        raise Internal("Publishing is unavailable on this relay (walkthrough module missing).")
    try:
        await guarded(p.publisher(doc_id, revision), "publishing")
    except LookupError as exc:
        raise NotFound(str(exc)) from exc
    except ValueError as exc:  # Part 5 re-verifies and refuses with readable lines
        raise Conflict("Approval refused.", detail=_reasons(str(exc))) from exc
    walk = await load_walkthrough(p, doc_id, revision)
    log.info("published %s rev %s (%d steps)", doc_id, revision, walk.total if walk else 0)
    return ApproveResult(doc_id=doc_id, revision=revision, steps=walk.steps if walk else [])
