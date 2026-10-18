"""POST /v1/ingest -- re-ingest /corpus through Part 5's ingest function. ADMIN_TOKEN only."""

from __future__ import annotations

import hmac
import inspect
import logging

from fastapi import APIRouter, Request

from ..config import REPO_ROOT
from ..main import error_response, trace_id_of

log = logging.getLogger("specs.ingest")
router = APIRouter()


def _token(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("x-admin-token", "")


@router.post("/v1/ingest")
async def ingest(request: Request):  # noqa: ANN201
    settings = request.app.state.settings
    p = request.app.state.pipeline
    trace_id = trace_id_of(request)
    expected = settings.admin_token.get_secret_value() if settings.admin_token else ""
    if not expected:
        resp = error_response(trace_id, "bad_request", "ingest disabled: ADMIN_TOKEN not set")
        resp.status_code = 403
        return resp
    if not hmac.compare_digest(_token(request).encode(), expected.encode()):
        log.warning("ingest rejected: bad admin token")
        resp = error_response(trace_id, "bad_request", "invalid admin token")
        resp.status_code = 401
        return resp
    if not p.real_db:
        return {"ok": True, "mock": True, "trace_id": trace_id}
    fn = getattr(p.db, "ingest_corpus", None)
    if fn is None:
        resp = error_response(trace_id, "internal", "db.ingest_corpus() not available yet")
        resp.status_code = 501
        return resp
    corpus = settings.corpus_dir or str(REPO_ROOT / "corpus")
    try:
        result = fn(corpus)
        if inspect.isawaitable(result):
            result = await result
    except Exception as exc:  # noqa: BLE001
        log.error("ingest failed: %s", type(exc).__name__)
        return error_response(trace_id, "db_down", f"ingest failed: {type(exc).__name__}")
    return {"ok": True, "mock": False, "trace_id": trace_id, "result": result}
