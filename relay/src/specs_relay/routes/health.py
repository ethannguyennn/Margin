from __future__ import annotations

import asyncio
import math

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .. import obs
from ..schemas import HealthResponse

router = APIRouter()


@router.get("/v1/health", response_model=HealthResponse)
async def health(request: Request, verbose: bool = False):
    p = request.app.state.pipeline
    settings = request.app.state.settings
    if not p.real_db:
        db = "mock"
    else:
        try:
            db = str(await asyncio.wait_for(p.db.ping(), timeout=2.0))
        except Exception:  # noqa: BLE001
            db = "down"
    # Conversion and notification availability must not label a real answer path as mock.
    ask_components = {"all", "db", "transcribe", "retrieve", "generate", "intent",
                      "verify", "sanitize", "walkthrough", "command"}
    ask_mock = settings.mock_mode or not p.real_db or bool(ask_components.intersection(p.mocked))
    result = HealthResponse(ok=db != "down", mock=ask_mock, db=db, version=obs.version(settings))
    if not verbose:
        return result
    conversion_mock = settings.mock_mode or bool({"all", "convert", "verify_step", "render", "publish"}.intersection(p.mocked))
    return JSONResponse({**result.model_dump(), "ask_mock": ask_mock,
                         "conversion_mock": conversion_mock, "mocked": list(p.mocked),
                         "git_sha": settings.git_sha or None,
                         "gate": {"min_sim": p.min_sim if math.isfinite(p.min_sim) else None,
                                  "min_rrf": p.min_rrf if math.isfinite(p.min_rrf) else None},
                         **obs.quota_snapshot()})
