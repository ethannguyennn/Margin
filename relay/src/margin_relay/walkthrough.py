"""Assembly of complete walkthroughs and durable deviation records."""
from __future__ import annotations

import asyncio
import logging
import re

from . import db
from .notify import Notifier, get_notifier

log = logging.getLogger(__name__)


def step_from_chunk(chunk: dict):
    from .illustrations import graphic_for_chunk
    from .pipeline.sanitize import sanitize
    from .schemas import Step

    # One numbered action per section; source text is otherwise preserved.
    text = re.sub(r"^\s*\d+\.\s+", "", chunk["text"])
    body = sanitize(text).strip()
    glance = sanitize(chunk["heading"] or f"Step {chunk['section']}").strip()
    if not body or len(body) >= 450:
        # Never silently truncate a procedural warning or acceptance limit.
        raise ValueError(f"Step {chunk['chunk_id']} must have 1..449 sanitized body characters")
    if len(glance) >= 60:
        glance = glance[:56].rstrip() + "..."
    return Step(step_id=chunk["chunk_id"], label=chunk["section"], glance=glance, body=body,
                graphic_id=graphic_for_chunk(chunk))


async def build_walkthrough(doc_id: str, revision: str | None = None) -> dict:
    document = await db.document_for(doc_id, revision)
    if document is None:
        raise LookupError(f"Procedure {doc_id} was not found")
    # Pin the resolved revision so a status change cannot mix revisions.
    steps = await db.steps_for(doc_id, document["revision"])
    if not steps:
        raise LookupError(f"Procedure {doc_id} has no ordered steps")
    return {
        "doc_id": doc_id, "revision": document["revision"], "title": document["title"],
        "total": len(steps), "index": 0,
        "steps": [step.model_dump() for step in steps],
    }


async def log_deviation(session_id, text: str, doc_id: str | None = None,
                        step_id: str | None = None, *, notifier: Notifier | None = None) -> dict:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Deviation text must not be blank")
    if step_id is not None and (doc_id is None or not step_id.startswith(doc_id + ":")):
        raise ValueError("step_id must belong to doc_id")
    deviation_id = await db.next_deviation_id()
    # insert_deviation returns after committing. Notification cannot roll it back.
    await db.insert_deviation(deviation_id, session_id, doc_id, step_id, text, notified=False)
    notified = False
    try:
        notifier = notifier if notifier is not None else get_notifier()
        async with asyncio.timeout(2):
            notified = await notifier.notify(deviation_id, text) is True
    except Exception as exc:
        log.warning("Notification failed for %s (%s)", deviation_id, type(exc).__name__)
    if notified:
        try:
            await db.set_deviation_notified(deviation_id, True)
        except Exception as exc:
            # Conservative: report the durable false state if the update failed.
            log.warning("Notification status not stored for %s (%s)", deviation_id, type(exc).__name__)
            notified = False
    return {"deviation_id": deviation_id, "notified": notified}
