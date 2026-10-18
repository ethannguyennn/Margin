"""Diagram tiles (lens) and previews (portal). BUILD-PLAN-V2 sections 4-5.

    GET /v1/diagrams/{id}              device token -> DiagramImage  (approved + effective or
                                                       pinned by an open assignment; 404 otherwise)
    GET /v1/diagrams/{id}/preview.png  portal token -> image/png     (lens-exact, drafts too)

Tiles are served exactly as Part 4's renderer stored them, base64-encoded; the
relay never re-encodes (the byte format is Part 2's day-one proof).
"""

from __future__ import annotations

import base64
import struct

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from ..auth import device_auth, portal_auth, require_device, require_portal
from ..schemas import DiagramImage, DiagramTile
from .common import NotFound, guarded

router = APIRouter()

TILE_W, TILE_H = 288, 144


def tile_size(data: bytes) -> tuple[int, int]:
    """PNG tiles carry their size; raw grey tiles are always 288 x 144."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    return TILE_W, TILE_H


@router.get("/v1/diagrams/{diagram_id}", response_model=DiagramImage,
             dependencies=[Depends(device_auth)])
async def diagram(diagram_id: str, request: Request) -> DiagramImage:
    await require_device(request)
    p = request.app.state.pipeline
    row = await guarded(p.db.get_diagram(diagram_id, approved_only=True), "loading the diagram")
    if row is None:
        raise NotFound("No approved diagram with that id.")
    tiles = []
    for slot, data in enumerate(list(row["tiles"])[:2]):
        data = bytes(data)
        width, height = tile_size(data)
        tiles.append(DiagramTile(slot=slot, width=width, height=height,
                                 image=base64.b64encode(data).decode("ascii")))
    return DiagramImage(diagram_id=diagram_id, tiles=tiles)


@router.get("/v1/diagrams/{diagram_id}/preview.png",
             dependencies=[Depends(portal_auth)])
async def preview(diagram_id: str, request: Request) -> Response:
    require_portal(request)
    p = request.app.state.pipeline
    row = await guarded(p.db.get_diagram(diagram_id, approved_only=False), "loading the diagram")
    if row is None:
        raise NotFound("No diagram with that id.")
    return Response(content=bytes(row["preview_png"]), media_type="image/png",
                    headers={"cache-control": "no-store"})
