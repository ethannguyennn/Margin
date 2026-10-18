"""Workspaces: an admin creates one in the portal and gets its code; workers type that
code in the Even app (POST /v1/devices/join) so their glasses answer from its SOPs.

    POST /v1/orgs      open             -> OrgInfo (the code opens the portal too)
    GET  /v1/orgs/me   workspace code   -> OrgInfo
"""

from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, Depends, Request

from ..auth import portal_auth, require_portal
from ..org import DEFAULT_ORG
from ..pipeline import BadRequest, DbDown
from ..schemas import PAIR_CODE_ALPHABET, OrgCreate, OrgInfo
from .common import NotFound, guarded

log = logging.getLogger("specs.orgs")
router = APIRouter()

CODE_LENGTH = 6
CREATE_ATTEMPTS = 8


def new_join_code() -> str:
    return "".join(secrets.choice(PAIR_CODE_ALPHABET) for _ in range(CODE_LENGTH))


@router.post("/v1/orgs", response_model=OrgInfo)
async def create_org(req: OrgCreate, request: Request) -> OrgInfo:
    request.app.state.pair_limiter.check(f"org:{request.client.host if request.client else ''}")
    p = request.app.state.pipeline
    for attempt in range(CREATE_ATTEMPTS):
        try:
            row = await p.db.create_org(req.name, new_join_code())
            break
        except ValueError as exc:
            if "name" in str(exc).lower():
                raise BadRequest(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - a join-code collision: draw another
            if attempt == CREATE_ATTEMPTS - 1:
                raise DbDown(f"could not create the workspace: {type(exc).__name__}") from exc
    else:
        raise DbDown("could not draw a free workspace code")
    log.info("workspace %s created", row["org_id"])
    return OrgInfo(**row)


@router.get("/v1/orgs/me", response_model=OrgInfo, dependencies=[Depends(portal_auth)])
async def my_org(request: Request) -> OrgInfo:
    require_portal(request)
    p = request.app.state.pipeline
    row = await guarded(p.db.org_by_id(getattr(request.state, "portal_org", None) or DEFAULT_ORG),
                        "loading the workspace")
    if row is None:
        raise NotFound("The workspace no longer exists.")
    return OrgInfo(**row)
