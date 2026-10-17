from __future__ import annotations

from fastapi import APIRouter, Request

from ..main import error_response, trace_id_of
from ..schemas import Procedure, Step

router = APIRouter()


@router.get("/v1/procedures", response_model=list[Procedure])
async def list_procedures(request: Request):  # noqa: ANN201
    p = request.app.state.pipeline
    try:
        rows = await p.db.list_procedures()
    except Exception as exc:  # noqa: BLE001
        return error_response(trace_id_of(request), "db_down",
                              f"could not list procedures: {type(exc).__name__}")
    return [Procedure.model_validate(r, from_attributes=True) for r in rows]


@router.get("/v1/procedures/{doc_id}/steps", response_model=list[Step])
async def procedure_steps(doc_id: str, request: Request, revision: str | None = None):  # noqa: ANN201
    p = request.app.state.pipeline
    try:
        steps = await p.retriever.steps_for(doc_id, revision or None)
    except Exception as exc:  # noqa: BLE001
        return error_response(trace_id_of(request), "db_down",
                              f"could not load steps: {type(exc).__name__}")
    return [Step.model_validate(s, from_attributes=True) for s in steps]
