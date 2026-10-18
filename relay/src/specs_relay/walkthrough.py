"""Assembly of complete walkthroughs and durable deviation records."""
from __future__ import annotations

import asyncio
import logging
import re

from . import db
from .notify import Notifier, get_notifier

log = logging.getLogger(__name__)


def step_from_chunk(chunk: dict):
    from .pipeline.sanitize import sanitize
    from .schemas import Step

    # One numbered action per section; source text is otherwise preserved.
    text = re.sub(r"^\s*\d+\.\s+", "", chunk["text"])
    authored = chunk.get("body") is not None
    body = sanitize(chunk["body"] if authored else text).strip()
    glance = sanitize(chunk.get("glance") or chunk["heading"] or f"Step {chunk['section']}").strip()
    cap = 450 if authored else 449
    if not body or len(body) > cap:
        # Never silently truncate a procedural warning or acceptance limit.
        raise ValueError(f"Step {chunk['chunk_id']} must have 1..{cap} sanitized body characters")
    if len(glance) > 60 and authored:
        raise ValueError("Published glance exceeds 60 characters")
    if len(glance) >= 60 and not authored:
        glance = glance[:56].rstrip() + "..."
    extras = {k: chunk[k] for k in ("warning", "checkpoint", "diagram") if chunk.get(k) is not None}
    from .illustrations import graphic_for_chunk
    extras["graphic_id"] = graphic_for_chunk(chunk)
    return Step(step_id=chunk["chunk_id"], label=chunk["section"], glance=glance, body=body,
                source_text=chunk["text"], **extras)


def verify_for_publication(step, material):
    from .convert.verify_step import verify_step
    return verify_step(step, material)


async def publish_draft(doc_id, revision: str | None = None, *, settings=None, embedder=None) -> dict:
    """Verify durable source, embed, then atomically publish an unchanged snapshot.

    Accept a shared ProcedureDraft as a convenience to route callers, but always
    reload it: the submitted object is never the publication authority.
    """
    if not isinstance(doc_id, str):
        doc_id, revision = doc_id.doc_id, doc_id.revision
    if revision is None:
        raise ValueError("Publishing requires an explicit revision")
    draft = await db.get_draft(doc_id, revision)
    if draft is None:
        raise LookupError("Draft was not found")
    if draft.status not in {"ready", "approved"} or not draft.steps:
        raise ValueError("A ready draft with at least one step is required")
    labels = [s.label for s in draft.steps]
    if len(set(labels)) != len(labels) or any(not label.strip() or ":" in label for label in labels):
        raise ValueError("Step labels must be unique, nonempty and contain no colon")
    if any(f"warning-{i}" in labels for i in range(1, len(draft.warnings) + 1)):
        raise ValueError("Step labels conflict with document warning sections")
    material = await db.get_material_text(draft.material_id)
    if material is None:
        raise ValueError("Source material text is missing")
    reasons = []
    for step in draft.steps:
        result = verify_for_publication(step, material)
        if not step.verify.ok or not result.ok or not step.quotes or any(not q.strip() for q in step.quotes):
            reasons.append(f"Step {step.label}: {result.reason or step.verify.reason or 'missing source quotes'}")
        if step.diagram is not None and (not step.diagram_id or not step.diagram_approved):
            reasons.append(f"Step {step.label}: diagram needs approval or detachment")
        if step.diagram is None and step.diagram_id:
            reasons.append(f"Step {step.label}: detach the diagram identifier as well")
    from .pipeline.verify import quote_in_text
    source = "\n".join(page.text for page in material.pages)
    for warning in draft.warnings:
        if not quote_in_text(warning, source):
            reasons.append("A document warning is not quoted from the source material")
    if reasons:
        raise ValueError("\n".join(reasons))
    chunks = []
    for index, step in enumerate(draft.steps, 1):
        chunks.append({
            "chunk_id": f"{doc_id}:{revision}:{step.label}", "doc_id": doc_id, "revision": revision,
            "section": step.label, "is_step": True, "step_order": index, "heading": step.glance,
            "text": "\n".join(step.quotes), "glance": step.glance, "body": step.body,
            "warning": step.warning, "checkpoint": step.checkpoint, "diagram_id": step.diagram_id,
        })
    for index, warning in enumerate(draft.warnings, 1):
        section = f"warning-{index}"
        chunks.append({"chunk_id": f"{doc_id}:{revision}:{section}", "doc_id": doc_id, "revision": revision,
                       "section": section, "is_step": False, "step_order": None,
                       "heading": "Warning", "text": warning})
    # Reuse the same batched SDK helper and settings as the v1 corpus seed.
    seed = db.seed_module()
    settings = settings if settings is not None else db.get_settings()
    vectors = await (embedder or seed.gemini_embeddings)(
        [f"{doc_id} rev {revision}: {draft.title}\nSec {c['section']} {c['heading']}\n{c['text']}" for c in chunks],
        settings, 32)
    if len(vectors) != len(chunks):
        raise ValueError("Embedding count must match published chunks")
    dimension = db.embedding_dimension(db.setting(settings, "EMBED_DIM"))
    for chunk, vector in zip(chunks, vectors, strict=True):
        db.vector_literal(vector, dimension)
        chunk["embedding"] = vector
    return await db.publish_prepared(draft, chunks, material)


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
