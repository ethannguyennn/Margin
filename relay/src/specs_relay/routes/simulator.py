"""Workspace-authenticated browser simulator adapters over the real lens handlers.

The browser has no device identity. Portal auth scopes reads and questions to its
workspace without creating a fake device, assignment or progress event.
"""
from __future__ import annotations

import base64

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from ..auth import portal_auth
from ..schemas import AskRequest, AskResponse, DiagramImage, DiagramTile, Procedure
from .ask import ask
from .common import NotFound, guarded
from .diagrams import tile_size

router = APIRouter(prefix="/v1/simulator", dependencies=[Depends(portal_auth)])


@router.post("/ask", response_model=AskResponse)
async def simulator_ask(req: AskRequest, request: Request, background: BackgroundTasks):
    return await ask(req, request, background)


@router.get("/diagrams/{diagram_id}", response_model=DiagramImage)
async def simulator_diagram(diagram_id: str, request: Request):
    db = request.app.state.pipeline.db
    row = await guarded(db.get_diagram(diagram_id, approved_only=True),
                        "loading the simulator diagram")
    if row is None:
        raise NotFound("No approved diagram with that id.")
    # get_diagram's shared storage lookup is not tenant scoped. A simulator has
    # no pinned device assignment: only its workspace's effective revisions qualify.
    procedures = await guarded(db.list_procedures(), "checking the simulator workspace")
    owned = [Procedure.model_validate(p, from_attributes=True) for p in procedures]
    if not any(p.doc_id == row["doc_id"] and p.revision == row["revision"]
               and p.status == "effective" for p in owned):
        raise NotFound("No approved diagram with that id.")
    return DiagramImage(diagram_id=diagram_id, tiles=[
        DiagramTile(slot=slot, width=tile_size(bytes(data))[0], height=tile_size(bytes(data))[1],
                    image=base64.b64encode(bytes(data)).decode("ascii"))
        for slot, data in enumerate(list(row["tiles"])[:2])])
