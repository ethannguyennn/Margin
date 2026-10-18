"""Task progress. BUILD-PLAN-V2 section 5.

    POST /v1/progress            device token -> {accepted: n}   batched, idempotent
    GET  /v1/progress?since=     portal token -> board rows      (portal polls every 3 s)

Writes are scoped to the authenticated device inside Part 5's insert_progress and
never raise into the request path (analytics rule). Part 5 caps one insert at 100
events; Part 2 may replay up to 200 after being offline, so batches are split.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Request

from ..auth import device_auth, portal_auth, require_device, require_portal
from ..schemas import BoardRow, ProgressAccepted, ProgressBatch
from .common import guarded

router = APIRouter()

DB_BATCH = 100


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


@router.post("/v1/progress", response_model=ProgressAccepted,
             dependencies=[Depends(device_auth)])
async def report(batch: ProgressBatch, request: Request) -> ProgressAccepted:
    device, _token = await require_device(request)
    p = request.app.state.pipeline
    accepted = 0
    for i in range(0, len(batch.events), DB_BATCH):
        chunk = batch.events[i:i + DB_BATCH]
        try:
            accepted += int(await p.db.insert_progress(chunk, device_id=device["device_id"]) or 0)
        except Exception:  # noqa: BLE001 - progress is best effort; the client resends safely
            pass
    return ProgressAccepted(accepted=accepted)


@router.get("/v1/progress", response_model=list[BoardRow],
             dependencies=[Depends(portal_auth)])
async def board(request: Request, since: float | None = None) -> list[BoardRow]:
    require_portal(request)
    p = request.app.state.pipeline
    rows = await guarded(p.db.progress_board(since), "loading the board")
    return [BoardRow.model_validate(_plain(dict(r))) for r in rows]
