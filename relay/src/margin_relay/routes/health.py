from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request

from .. import obs
from ..schemas import HealthResponse

router = APIRouter()


@router.get("/v1/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    p = request.app.state.pipeline
    settings = request.app.state.settings
    if not p.real_db:
        db = "mock"
    else:
        try:
            db = str(await asyncio.wait_for(p.db.ping(), timeout=2.0))
        except Exception:  # noqa: BLE001
            db = "down"
    return HealthResponse(ok=db != "down", mock=settings.mock_mode or bool(p.mocked), db=db,
                          version=obs.version(settings))
