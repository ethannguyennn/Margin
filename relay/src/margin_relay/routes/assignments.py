"""Task assignment. BUILD-PLAN-V2 section 5.

    POST /v1/assignments       portal token -> Assignment
    GET  /v1/assignments/next  device token -> Assignment | 204   (polled every 10 s in IDLE)

The walkthrough comes from the one shared builder (routes/common.py), so a
published procedure, a seeded v1 SOP and a walk-me-through answer are one code
path. The revision is pinned when the task is assigned (Part 5).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from ..auth import device_auth, portal_auth, require_device, require_portal
from ..schemas import AssignRequest, Assignment
from .common import Internal, NotFound, guarded, iso, load_walkthrough

log = logging.getLogger("margin.assignments")
router = APIRouter()


@router.post("/v1/assignments", response_model=Assignment,
             dependencies=[Depends(portal_auth)])
async def assign(req: AssignRequest, request: Request) -> Assignment:
    require_portal(request)
    p = request.app.state.pipeline
    try:
        assignment_id = await guarded(
            p.db.create_assignment(req.device_id, req.doc_id, req.revision), "assigning")
    except LookupError as exc:
        raise NotFound("That lens is not paired, or the procedure is not published.") from exc
    except ValueError as exc:
        raise NotFound(str(exc)) from exc
    walk = await load_walkthrough(p, req.doc_id, req.revision)
    if walk is None:
        raise Internal(f"{req.doc_id} has no steps to assign")
    log.info("assigned %s rev %s to %s as %s", walk.doc_id, walk.revision, req.device_id, assignment_id)
    return Assignment(assignment_id=assignment_id,
                      walkthrough=walk.model_copy(update={"assignment_id": assignment_id}),
                      assigned_at=datetime.now(timezone.utc).isoformat())


@router.get("/v1/assignments/next", response_model=Assignment,
            responses={204: {"description": "No task waiting"}},
             dependencies=[Depends(device_auth)])
async def next_assignment(request: Request) -> Assignment | Response:
    device, _token = await require_device(request)
    p = request.app.state.pipeline
    row = await guarded(p.db.next_assignment(device["device_id"]), "loading the next task")
    if row is None:
        return Response(status_code=204)
    walk = await load_walkthrough(p, row["doc_id"], row["revision"])
    if walk is None:
        raise Internal(f"assigned procedure {row['doc_id']} rev {row['revision']} has no steps")
    return Assignment(assignment_id=row["assignment_id"],
                      walkthrough=walk.model_copy(update={"assignment_id": row["assignment_id"]}),
                      assigned_at=iso(row.get("assigned_at")) or datetime.now(timezone.utc).isoformat())
