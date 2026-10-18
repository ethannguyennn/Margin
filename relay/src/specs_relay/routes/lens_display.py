"""Ephemeral acknowledged lens frames. Single relay process; no audio or frame history."""
from __future__ import annotations

import time
import uuid
import base64
import io
from collections import OrderedDict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .. import org
from ..auth import (Unauthorized, bearer, device_auth, device_org, portal_auth, token_hash)

router = APIRouter(prefix="/v1/lens")
LIVE_SECONDS = 12


class Frame(BaseModel):
    model_config = ConfigDict(extra="forbid")
    header: str = Field(max_length=2000)
    main: str = Field(max_length=2000)
    footer: str = Field(max_length=2000)
    graphic_id: str | None = Field(default=None, max_length=120)


class Tile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slot: Literal[0, 1]
    width: Literal[288]
    height: Literal[144]
    image: str = Field(max_length=90000, pattern=r"^[A-Za-z0-9+/]*={0,2}$")

    @model_validator(mode="after")
    def valid_bytes(self):
        try:
            data = base64.b64decode(self.image, validate=True)
            if data.startswith(b"\x89PNG\r\n\x1a\n"):
                from PIL import Image  # optional on mock-only boot; loaded only for PNG uploads
                with Image.open(io.BytesIO(data)) as image:
                    if image.size != (288, 144) or image.format != "PNG":
                        raise ValueError("Invalid PNG dimensions")
                    image.verify()
            elif len(data) not in {288 * 144, 288 * 144 // 2}:
                raise ValueError("Invalid raw tile size")
        except Exception as exc:
            raise ValueError("Expected a 288x144 PNG or raw grey tile") from exc
        return self


class Diagram(BaseModel):
    model_config = ConfigDict(extra="forbid")
    diagram_id: str = Field(max_length=120)
    tiles: list[Tile] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def unique_slots(self):
        if {t.slot for t in self.tiles} != {0, 1}:
            raise ValueError("Both diagram slots are required")
        return self


class DisplayUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stream_id: uuid.UUID
    sequence: int = Field(ge=1)
    connected: bool
    screen: str = Field(max_length=40, pattern=r"^[A-Z_]+$")
    frame: Frame
    diagram: Diagram | None = None


class DisplayFeeds:
    def __init__(self, clock=time.time):
        self.clock = clock
        self.rows: OrderedDict[str, dict] = OrderedDict()

    def prune(self):
        for key in list(self.rows):
            if self.clock() - self.rows[key]["seen"] > 600:
                del self.rows[key]
        while len(self.rows) >= 256:
            self.rows.popitem(last=False)


async def claimed(request: Request):
    device, _ = await device_auth(request)
    if not device.get("claimed_at"):
        raise Unauthorized("Join a workspace before sharing the lens display.")
    return device


async def viewer(request: Request):
    token = bearer(request)
    device = await request.app.state.pipeline.db.device_by_token(token_hash(token)) if token else None
    if device is not None:
        if not device.get("claimed_at"):
            raise Unauthorized("Join the glasses' workspace to view their display.")
        org.use(device_org(device))
    else:
        await portal_auth(request)


@router.post("/display/stream")
async def start(request: Request, device=Depends(claimed)):
    feeds = request.app.state.display_feeds
    feeds.prune()
    stream = str(uuid.uuid4())
    feeds.rows[device["device_id"]] = dict(stream=stream, org=org.current(), sequence=0,
                                        seen=feeds.clock(), update=None)
    return {"stream_id": stream}


@router.put("/display")
async def publish(body: DisplayUpdate, request: Request, device=Depends(claimed)):
    feeds = request.app.state.display_feeds
    row = feeds.rows.get(device["device_id"])
    if row is None or feeds.clock() - row["seen"] > 600:
        raise HTTPException(410, "Open a new display stream.")
    if row["stream"] != str(body.stream_id) or row["org"] != org.current() or body.sequence <= row["sequence"]:
        raise HTTPException(409, "Superseded display update.")
    row.update(sequence=body.sequence, seen=feeds.clock(), update=body.model_dump(exclude={"stream_id"}))
    feeds.rows.move_to_end(device["device_id"])
    return {"ok": True}


def snapshot(feeds, device):
    row = feeds.rows.get(device["device_id"])
    # Re-check current DB membership: moving a device never exposes an old workspace's frame.
    if row is None or row["org"] != org.current() or feeds.clock() - row["seen"] > 600:
        row = None
    update = row["update"] if row else None
    live = bool(update and update["connected"] and feeds.clock() - row["seen"] < LIVE_SECONDS)
    return {"device_id": device["device_id"], "worker_name": device.get("worker_name"),
            "live": live, "last_seen": row["seen"] if row else None,
            **(update or {})}


@router.get("/displays", dependencies=[Depends(viewer)])
async def devices(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    rows = await request.app.state.pipeline.db.list_devices()
    return [{k: v for k, v in snapshot(request.app.state.display_feeds, d).items()
             if k not in {"frame", "diagram"}} for d in rows if d.get("claimed_at")]


@router.get("/displays/{device_id}", dependencies=[Depends(viewer)])
async def display(device_id: str, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    rows = await request.app.state.pipeline.db.list_devices()
    device = next((d for d in rows if d["device_id"] == device_id and d.get("claimed_at")), None)
    if device is None:
        raise HTTPException(404, "No glasses in this workspace with that id.")
    return snapshot(request.app.state.display_feeds, device)
