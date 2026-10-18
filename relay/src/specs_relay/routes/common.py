"""Shared by the v2 routes: typed route errors and the one walkthrough builder.

``load_walkthrough`` is the single code path for a procedure's steps, used by
``/v1/ask`` (walk me through) and ``GET /v1/assignments/next`` alike, so a
published draft, a seeded v1 SOP and a walkthrough answer carry the same v2
extras (warning, checkpoint, approved diagram).
"""

from __future__ import annotations

from collections.abc import Awaitable
from datetime import datetime
from typing import Any, TypeVar

from ..pipeline import DbDown, PipelineError
from ..schemas import Step, Walkthrough


T = TypeVar("T")


class NotFound(PipelineError):
    code = "not_found"


class Conflict(PipelineError):
    code = "conflict"

    def __init__(self, message: str, detail: Any = None) -> None:
        super().__init__(message)
        self.detail = detail


class PayloadTooLarge(PipelineError):
    code = "payload_too_large"


class UnsupportedMedia(PipelineError):
    code = "unsupported_media_type"


class Internal(PipelineError):
    code = "internal"


async def guarded(awaitable: Awaitable[T], what: str) -> T:
    """Await a Part 5 db call. Its LookupError / ValueError (and our typed errors) pass
    through for the route to map; anything else is the database failing -> db_down."""
    try:
        return await awaitable
    except (LookupError, ValueError, PipelineError):
        raise
    except Exception as exc:
        raise DbDown(f"{what} failed: {type(exc).__name__}") from exc


def iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, datetime) else str(value)


def sanitized_step(p: Any, s: Step) -> Step:
    """Lens-safe copy of a step. Re-validated (not model_copy): sanitizing can lengthen
    text, and the caps must bite rather than truncate."""
    def clean(value: str | None) -> str | None:
        return p.sanitize(value).strip() if value else value

    return Step(step_id=s.step_id, label=s.label, glance=clean(s.glance) or "",
                body=clean(s.body) or "", warning=clean(s.warning), checkpoint=clean(s.checkpoint),
                diagram=s.diagram, graphic_id=s.graphic_id)


async def doc_title(p: Any, doc_id: str, revision: str | None) -> str | None:
    try:
        for row in await p.db.list_procedures():
            get = row.get if isinstance(row, dict) else (lambda k, r=row: getattr(r, k, None))
            if get("doc_id") == doc_id and (revision is None or get("revision") == revision):
                return get("title")
    except Exception:  # noqa: BLE001 - a title is cosmetic
        return None
    return None


async def load_walkthrough(p: Any, doc_id: str, revision: str | None, *,
                           title_hint: str | None = None) -> Walkthrough | None:
    """Every step of ``doc_id`` (pinned ``revision``, else the effective one), or None.

    Real mode: Part 5's ``walkthrough.build_walkthrough`` (LookupError -> None; an
    over-cap step is a corpus problem -> Internal, never truncated). Mock mode: the
    retriever's ``steps_for``.
    """
    if p.walkthrough is not None:
        try:
            built = await p.walkthrough.build_walkthrough(doc_id, revision)
        except LookupError:
            return None
        except ValueError as exc:
            raise Internal(f"procedure {doc_id} violates the step caps; fix it in the portal") from exc
        except Exception as exc:
            raise DbDown(f"loading the procedure failed: {type(exc).__name__}") from exc
        steps = [Step.model_validate(s) for s in built["steps"]]
        rev, title = built["revision"], built["title"]
    else:
        try:
            steps = list(await p.retriever.steps_for(doc_id, revision))
        except Exception as exc:
            raise DbDown(f"loading steps failed: {type(exc).__name__}") from exc
        if not steps:
            return None
        rev = revision or steps[0].step_id.split(":")[1]
        title = title_hint or await doc_title(p, doc_id, rev) or doc_id
    if not steps:
        return None
    steps = [sanitized_step(p, s) for s in steps]
    return Walkthrough(doc_id=doc_id, revision=rev, title=p.sanitize(title).strip() or doc_id,
                       total=len(steps), index=0, steps=steps)
