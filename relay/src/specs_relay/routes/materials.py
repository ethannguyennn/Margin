"""Material uploads (portal). README-PART-3 section 6.

    POST /v1/materials           multipart: file, doc_id, title, revision -> {material_id, status}
    GET  /v1/materials/{id}                                               -> MaterialStatus
    GET  /v1/materials/{id}/text                                          -> MaterialText

Upload rules, all checked *before* anything is stored: portal token, size
(MAX_UPLOAD_MB, from Content-Length and again from the bytes read), identifiers
(doc_id ``^[A-Z]{2,5}-\\d{3}$``, revision ``^[A-Z0-9]{1,3}$``, title <= 120), and
the type from the file's magic bytes (not just its header), which must agree
with the file extension. Then the conversion job starts in the background.
Synthetic material only: enforced by people, stated in the portal UI.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from starlette.datastructures import UploadFile

from ..auth import portal_auth, require_portal
from ..pipeline import BadRequest, DbDown
from ..schemas import (
    DOC_ID_PATTERN,
    REVISION_PATTERN,
    TITLE_MAX,
    MaterialCreated,
    MaterialLibrary,
    MaterialStatus,
    MaterialText,
)
from .common import NotFound, PayloadTooLarge, UnsupportedMedia, guarded

log = logging.getLogger("specs.materials")
router = APIRouter()

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MARKDOWN = "text/markdown"
TEXT = "text/plain"
PNG = "image/png"
JPEG = "image/jpeg"
ALLOWED = {PDF, DOCX, MARKDOWN, TEXT, PNG, JPEG}
EXTENSIONS = {".pdf": PDF, ".docx": DOCX, ".md": MARKDOWN, ".markdown": MARKDOWN, ".txt": TEXT,
              ".png": PNG, ".jpg": JPEG, ".jpeg": JPEG}


def material_store(request: Request):
    """Real uploads must never silently fall back to a process-local mock database."""
    p = request.app.state.pipeline
    if not request.app.state.settings.mock_mode and not p.real_db:
        raise DbDown("Persistent upload storage is unavailable. No file was saved; try again later.")
    return p.db


def _extension(filename: str) -> str:
    m = re.search(r"\.[A-Za-z0-9]+$", filename or "")
    return m.group(0).lower() if m else ""


def sniff(data: bytes, filename: str) -> str | None:
    """The MIME type from the content itself, or None if it is not an allowed type."""
    if data.startswith(b"%PDF-"):
        return PDF
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if data.startswith(b"\xff\xd8\xff"):
        return JPEG
    if data.startswith(b"PK\x03\x04"):
        try:
            names = set(zipfile.ZipFile(io.BytesIO(data)).namelist())
        except zipfile.BadZipFile:
            return None
        return DOCX if {"[Content_Types].xml", "word/document.xml"} <= names else None
    head = data[:65536]
    if b"\x00" in head:
        return None
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return MARKDOWN if _extension(filename) in (".md", ".markdown") else TEXT


@router.post("/v1/materials", status_code=202, response_model=MaterialCreated,
             dependencies=[Depends(portal_auth)])
async def upload(request: Request) -> JSONResponse:
    require_portal(request)  # before the body is read
    store = material_store(request)
    settings, p = request.app.state.settings, request.app.state.pipeline
    limit = settings.max_upload_mb * 1024 * 1024
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit + 64 * 1024:
        raise PayloadTooLarge(f"The file is over the {settings.max_upload_mb} MB limit.")
    try:
        form = await request.form(max_files=1, max_fields=8)
    except Exception as exc:  # noqa: BLE001 - malformed multipart
        raise BadRequest("Send multipart/form-data with file, doc_id, title and revision.") from exc
    upload_file = form.get("file")
    if not isinstance(upload_file, UploadFile):
        raise BadRequest("A file is required.")
    doc_id = str(form.get("doc_id") or "").strip()
    title = str(form.get("title") or "").strip()
    revision = str(form.get("revision") or "").strip()
    if not re.fullmatch(DOC_ID_PATTERN, doc_id):
        raise BadRequest("Document ID must look like SOP-150 (2-5 capital letters, a dash, 3 digits).")
    if not re.fullmatch(REVISION_PATTERN, revision):
        raise BadRequest("Revision must be 1-3 capital letters or digits, e.g. A.")
    if not title or len(title) > TITLE_MAX:
        raise BadRequest(f"A title of 1-{TITLE_MAX} characters is required.")
    data = await upload_file.read(limit + 1)
    if len(data) > limit:
        raise PayloadTooLarge(f"The file is over the {settings.max_upload_mb} MB limit.")
    if not data:
        raise BadRequest("The file is empty.")
    filename = (upload_file.filename or "upload").replace("\\", "/").rsplit("/", 1)[-1][:200]
    mime = sniff(data, filename)
    expected = EXTENSIONS.get(_extension(filename))
    if mime is None or mime not in ALLOWED:
        raise UnsupportedMedia("Upload a PDF, DOCX, Markdown, text, PNG or JPEG file.")
    if expected is not None and expected != mime and {expected, mime} != {MARKDOWN, TEXT}:
        raise UnsupportedMedia("The file's contents do not match its extension.")
    try:
        material_id = await guarded(
            store.insert_material(filename, mime, data, doc_id, revision, title), "storing the upload")
    except ValueError as exc:
        raise BadRequest(str(exc)) from exc
    request.app.state.jobs.start(material_id, data, mime, doc_id, revision, title)
    log.info("material %s stored (%s, %d bytes); conversion started", material_id, mime, len(data))
    return JSONResponse(MaterialCreated(material_id=material_id).model_dump(), status_code=202,
                        headers={"Location": f"/v1/materials/{material_id}", "Cache-Control": "no-store"})


@router.get("/v1/materials", response_model=MaterialLibrary, dependencies=[Depends(portal_auth)])
async def library(request: Request, response: Response, q: str = Query(default="", max_length=120),
                  limit: int = Query(default=50, ge=1, le=100),
                  offset: int = Query(default=0, ge=0)) -> MaterialLibrary:
    require_portal(request)
    rows = await guarded(material_store(request).list_materials(query=q, limit=limit + 1, offset=offset),
                         "loading saved uploads")
    response.headers["Cache-Control"] = "no-store"
    return MaterialLibrary(items=rows[:limit], next_offset=offset + limit if len(rows) > limit else None)


@router.get("/v1/materials/{material_id}/file", dependencies=[Depends(portal_auth)])
async def original(material_id: str, request: Request) -> Response:
    require_portal(request)
    row = await guarded(material_store(request).get_material(material_id, include_bytes=True),
                        "loading the original upload")
    if row is None:
        raise NotFound("No material with that id.")
    # Attachment + nosniff prevents uploaded text/SVG-like content from executing in our origin.
    filename = (row["filename"] or "upload").replace("\\", "/").rsplit("/", 1)[-1]
    return Response(bytes(row["bytes"]), media_type=row["mime"], headers={
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename, safe=""),
        "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
    })


@router.get("/v1/materials/{material_id}", response_model=MaterialStatus,
             dependencies=[Depends(portal_auth)])
async def status(material_id: str, request: Request) -> MaterialStatus:
    require_portal(request)
    p = request.app.state.pipeline
    row = await guarded(p.db.get_material(material_id), "loading the material")
    if row is None:
        raise NotFound("No material with that id.")
    return MaterialStatus(material_id=row["material_id"], status=row["status"], error=row.get("error"),
                          doc_id=row["doc_id"], revision=row["revision"], title=row.get("title"),
                          filename=row.get("filename"))


@router.get("/v1/materials/{material_id}/text", response_model=MaterialText,
             dependencies=[Depends(portal_auth)])
async def text(material_id: str, request: Request) -> MaterialText:
    require_portal(request)
    p = request.app.state.pipeline
    extracted = await guarded(p.db.get_material_text(material_id), "loading the material text")
    if extracted is None:
        raise NotFound("No extracted text for that material yet.")
    return extracted
