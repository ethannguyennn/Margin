from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Request

from ..main import error_response, trace_id_of
from ..pipeline import DbDown
from ..schemas import DeviationRequest, DeviationResponse

log = logging.getLogger("margin.deviation")
router = APIRouter()

NOTIFY_TIMEOUT_S = 3.0


async def log_deviation(p: Any, *, session_id: str, text: str, doc_id: str | None,
                        step_id: str | None) -> DeviationResponse:
    """Allocate an id, alert the supervisor, store the record with the alert result.

    The record is the compliance artifact; the alert is a convenience. A notifier
    failure still stores the row with notified=false. A DB failure raises DbDown.
    """
    try:
        deviation_id = await p.db.next_deviation_id()
    except Exception as exc:
        raise DbDown(f"could not allocate a deviation id: {type(exc).__name__}") from exc
    notified = False
    try:
        notified = bool(await asyncio.wait_for(p.notifier.notify(deviation_id, text),
                                               timeout=NOTIFY_TIMEOUT_S))
    except Exception as exc:  # noqa: BLE001
        log.warning("notifier failed for %s: %s", deviation_id, type(exc).__name__)
    try:
        await p.db.insert_deviation(deviation_id=deviation_id, session_id=session_id,
                                    doc_id=doc_id, step_id=step_id, text=text, notified=notified)
    except Exception as exc:
        raise DbDown(f"could not store deviation {deviation_id}: {type(exc).__name__}") from exc
    return DeviationResponse(deviation_id=deviation_id, notified=notified)


@router.post("/v1/deviation", response_model=DeviationResponse)
async def deviation(req: DeviationRequest, request: Request):  # noqa: ANN201
    p = request.app.state.pipeline
    ctx = req.context
    try:
        return await log_deviation(
            p, session_id=str(req.session_id), text=req.text.strip(),
            doc_id=req.doc_id or (ctx.doc_id if ctx else None),
            step_id=req.step_id or (ctx.step_id if ctx else None))
    except DbDown as exc:
        return error_response(trace_id_of(request), "db_down", exc.message)
