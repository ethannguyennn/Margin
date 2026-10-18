"""Device pairing (lens), joining a workspace (Even app) and claiming (portal).

    POST /v1/devices/pair   open, rate-limited  -> Pairing (with the device_token, once)
    GET  /v1/devices/me     device token        -> Pairing (polled until claimed)
    POST /v1/devices/join   device token        -> Pairing: the worker typed the admin's
                                                   workspace code; the lens now uses its SOPs
    POST /v1/devices/claim  portal token        -> Pairing (device_token "") - the older
                                                   flow, the admin types the lens's code
    GET  /v1/devices        portal token        -> DeviceInfo[] (no tokens)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request

from ..auth import (
    client_key,
    device_auth,
    new_device_token,
    new_pair_code,
    portal_auth,
    require_device,
    require_portal,
    token_hash,
)
from ..pipeline import BadRequest, DbDown
from ..schemas import ClaimRequest, DeviceInfo, JoinRequest, Pairing, PairRequest
from .common import NotFound, guarded, iso

log = logging.getLogger("specs.devices")
router = APIRouter()

PAIR_ATTEMPTS = 8  # a fresh code per attempt; collisions only among open codes


def _expired(row: dict[str, Any], now: datetime) -> bool:
    expires = row.get("pair_expires")
    return expires is None or expires <= now


async def _workspace(p: Any, row: dict[str, Any]) -> str | None:
    if not row.get("org_id"):
        return None
    try:
        found = await p.db.org_by_id(row["org_id"])
    except Exception:  # noqa: BLE001 - the name is cosmetic
        return None
    return found["name"] if found else None


async def _pairing(p: Any, row: dict[str, Any], token: str) -> Pairing:
    return Pairing(device_id=row["device_id"], device_token=token, pair_code=row.get("pair_code") or "",
                   claimed=row.get("claimed_at") is not None, worker_name=row.get("worker_name"),
                   workspace=await _workspace(p, row))


@router.post("/v1/devices/pair", response_model=Pairing)
async def pair(req: PairRequest, request: Request) -> Pairing:
    request.app.state.pair_limiter.check(client_key(request))
    p, settings = request.app.state.pipeline, request.app.state.settings
    token = new_device_token()
    expires = datetime.now(timezone.utc) + timedelta(seconds=settings.pair_code_ttl_s)
    for attempt in range(PAIR_ATTEMPTS):
        code = new_pair_code()
        try:
            device_id = await p.db.create_device(token_hash(token), code, expires)
            break
        except Exception as exc:  # noqa: BLE001 - an open-code collision: draw another code
            if attempt == PAIR_ATTEMPTS - 1:
                raise DbDown(f"could not register the lens: {type(exc).__name__}") from exc
    log.info("lens %s registered, pair code issued (expires in %d s)", device_id,
             settings.pair_code_ttl_s)
    return Pairing(device_id=device_id, device_token=token, pair_code=code, claimed=False,
                   worker_name=None)


@router.get("/v1/devices/me", response_model=Pairing,
             dependencies=[Depends(device_auth)])
async def me(request: Request) -> Pairing:
    # No expiry here: a lens can join a workspace with its code any time after pairing.
    device, token = await require_device(request)
    return await _pairing(request.app.state.pipeline, device, token)


@router.post("/v1/devices/join", response_model=Pairing)
async def join(req: JoinRequest, request: Request) -> Pairing:
    # Not a route dependency: a lens that never paired (fresh browser preview) still
    # gets a clear 401, and the client pairs first, then joins.
    device, token = await require_device(request)
    p = request.app.state.pipeline
    name = (req.worker_name or "").strip() or device.get("worker_name") or "Worker"
    try:
        row = await guarded(p.db.join_device(token_hash(token), req.code, name), "joining")
    except ValueError as exc:
        raise BadRequest(str(exc)) from exc
    if row is None:
        raise NotFound("No workspace has that code. Check the code shown in the admin portal.")
    log.info("lens %s joined workspace %s", row["device_id"], row.get("org_id"))
    return await _pairing(p, row, token)


@router.post("/v1/devices/claim", response_model=Pairing,
             dependencies=[Depends(portal_auth)])
async def claim(req: ClaimRequest, request: Request) -> Pairing:
    require_portal(request)
    p = request.app.state.pipeline
    try:
        row = await guarded(p.db.claim_device(req.pair_code.strip().upper(), req.worker_name), "claim")
    except ValueError as exc:
        raise BadRequest(str(exc)) from exc
    if row is None:
        raise NotFound("No unclaimed lens shows that pair code. It may have expired: "
                       "reopen Specs on the glasses for a new one.")
    log.info("lens %s claimed", row["device_id"])
    # The device token never goes to the portal: whoever holds it can act as the lens.
    return Pairing(device_id=row["device_id"], device_token="", pair_code=row.get("pair_code") or "",
                   claimed=True, worker_name=row.get("worker_name"))


@router.get("/v1/devices", response_model=list[DeviceInfo],
             dependencies=[Depends(portal_auth)])
async def list_devices(request: Request) -> list[DeviceInfo]:
    require_portal(request)
    p = request.app.state.pipeline
    now = datetime.now(timezone.utc)
    rows = await guarded(p.db.list_devices(), "listing devices")
    out = []
    for row in rows:
        claimed = row.get("claimed_at") is not None
        open_code = row.get("pair_code") if not claimed and not _expired(row, now) else None
        out.append(DeviceInfo(device_id=row["device_id"], pair_code=open_code, claimed=claimed,
                              worker_name=row.get("worker_name"), claimed_at=iso(row.get("claimed_at")),
                              created_at=iso(row.get("created_at"))))
    return out
