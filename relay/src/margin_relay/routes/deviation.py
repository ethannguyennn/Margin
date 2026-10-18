from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Request

from ..main import error_response, trace_id_of
from ..pipeline import BadRequest, DbDown
from ..schemas import DeviationRequest, DeviationResponse

log = logging.getLogger("margin.deviation")
router = APIRouter()

NOTIFY_TIMEOUT_S = 2.0


async def log_deviation(p: Any, *, session_id: str, text: str, doc_id: str | None,
                        step_id: str | None) -> DeviationResponse:
    """Store the record, then alert the supervisor, then store the alert result.

    The record is the compliance artifact; the alert is a convenience, so the row is
    committed with notified=false *before* notifying. Real mode delegates to Part 5's
    walkthrough.log_deviation (same order). Invalid input raises BadRequest, a DB
    failure DbDown.
    """
    if p.walkthrough is not None:
        try:
            result = await p.walkthrough.log_deviation(session_id, text, doc_id, step_id,
                                                       notifier=p.notifier)
        except ValueError as exc:
            raise BadRequest(str(exc)) from exc
        except Exception as exc:
            raise DbDown(f"could not store deviation: {type(exc).__name__}") from exc
        return DeviationResponse.model_validate(result)

    try:
        deviation_id = await p.db.next_deviation_id()
        await p.db.insert_deviation(deviation_id=deviation_id, session_id=session_id,
                                    doc_id=doc_id, step_id=step_id, text=text, notified=False)
    except Exception as exc:
        raise DbDown(f"could not store deviation: {type(exc).__name__}") from exc
    notified = False
    try:
        notified = await asyncio.wait_for(p.notifier.notify(deviation_id, text),
                                          timeout=NOTIFY_TIMEOUT_S) is True
    except Exception as exc:  # noqa: BLE001
        log.warning("notifier failed for %s: %s", deviation_id, type(exc).__name__)
    if notified and hasattr(p.db, "set_deviation_notified"):
        try:
            await p.db.set_deviation_notified(deviation_id, True)
        except Exception as exc:  # noqa: BLE001 - report the durable false state
            log.warning("notified flag not stored for %s: %s", deviation_id, type(exc).__name__)
            notified = False
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
    except (BadRequest, DbDown) as exc:
        return error_response(trace_id_of(request), exc.code, exc.message)
