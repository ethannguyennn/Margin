"""The conversion job (README-PART-3 section 6): the second and last orchestrator.

    extract (Part 4) -> save MaterialText (Part 5)
    -> convert (Part 4) -> verify_step every step (Part 4, deterministic)
    -> render tiles + preview for every step with a diagram spec (Part 4) -> save diagram (Part 5)
    -> save draft, material status ready | failed (with a human-readable error)

Ponytail: no queue service. One relay process, ``asyncio.create_task`` tracked in
a dict so shutdown can cancel it, at most ``CONVERT_CONCURRENCY`` (2) at once, a
hard ``CONVERT_TIMEOUT_S`` per job. A job interrupted by a restart is marked
``failed`` on the next boot (``db.fail_interrupted_materials``). Each stage is a
Sentry span. Material text is never logged.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import sentry_sdk

from .pipeline import PipelineError
from .schemas import DraftStep, MaterialText, VerifyResult

log = logging.getLogger("specs.jobs")


def readable(exc: BaseException) -> str:
    """What the supervisor sees on the upload screen. Typed errors (ours and Part 4's,
    which carry ``code``) have messages written for people; anything else is generic."""
    if isinstance(exc, PipelineError):
        return exc.message[:300]
    if hasattr(exc, "code") and str(exc):
        return str(exc)[:300]
    return f"Conversion failed ({type(exc).__name__}). Upload the file again."


class JobRunner:
    def __init__(self, pipeline: Any, settings: Any) -> None:
        self.p = pipeline
        self.settings = settings
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self._sem: asyncio.Semaphore | None = None

    @property
    def sem(self) -> asyncio.Semaphore:
        if self._sem is None:  # created on first use, inside the running loop
            self._sem = asyncio.Semaphore(max(1, self.settings.convert_concurrency))
        return self._sem

    def start(self, material_id: str, data: bytes, mime: str, doc_id: str, revision: str,
              title: str) -> asyncio.Task[None]:
        task = asyncio.create_task(self.run(material_id, data, mime, doc_id, revision, title),
                                   name=f"convert {material_id}")
        self.tasks[material_id] = task
        task.add_done_callback(lambda _t: self.tasks.pop(material_id, None))
        return task

    async def run(self, material_id: str, data: bytes, mime: str, doc_id: str, revision: str,
                  title: str) -> None:
        try:
            async with self.sem:
                with sentry_sdk.start_transaction(op="conversion", name="convert material"):
                    await asyncio.wait_for(
                        self._convert(material_id, data, mime, doc_id, revision, title),
                        timeout=self.settings.convert_timeout_s)
        except asyncio.TimeoutError:
            log.warning("conversion %s timed out", material_id)
            await self._fail(material_id, f"Conversion timed out after {self.settings.convert_timeout_s:g} s. "
                                          "Upload a shorter document or try again.")
        except asyncio.CancelledError:
            await self._fail(material_id, "Conversion was interrupted because the relay shut down. Upload again.")
            raise
        except Exception as exc:  # noqa: BLE001 - every failure must end in `failed`, never stuck
            log.warning("conversion %s failed: %s", material_id, type(exc).__name__)
            sentry_sdk.capture_exception(exc)
            await self._fail(material_id, readable(exc))

    async def _convert(self, material_id: str, data: bytes, mime: str, doc_id: str, revision: str,
                       title: str) -> None:
        p = self.p
        with sentry_sdk.start_span(op="extract", name="extract"):
            text = await p.converter.extract(data, mime, material_id)
        await p.db.save_material_text(material_id, text)
        with sentry_sdk.start_span(op="convert", name="convert"):
            draft = await p.converter.convert(text, doc_id, revision, title)
        steps: list[DraftStep] = []
        with sentry_sdk.start_span(op="verify_step", name="verify_step"):
            for step in draft.steps:  # the orchestrator re-verifies: the converter is not the authority
                steps.append(step.model_copy(update={"verify": p.verify_step(step, text)}))
        with sentry_sdk.start_span(op="render", name="render diagrams"):
            for i, step in enumerate(steps):
                if step.diagram is not None:
                    steps[i] = await self._render(step, text, data, mime, doc_id, revision)
        draft = draft.model_copy(update={
            "doc_id": doc_id, "revision": revision, "title": title, "material_id": material_id,
            "status": "ready" if steps else "failed", "steps": steps})
        await p.db.save_draft(draft)
        if steps:
            await p.db.set_material_status(material_id, "ready")
            log.info("conversion %s ready: %d steps, %d verified", material_id, len(steps),
                     sum(1 for s in steps if s.verify.ok))
        else:
            await p.db.set_material_status(material_id, "failed",
                                           "No procedure steps were found in the material.")

    async def _render(self, step: DraftStep, text: MaterialText, data: bytes, mime: str,
                      doc_id: str, revision: str) -> DraftStep:
        p, spec = self.p, step.diagram
        assert spec is not None
        try:
            page_png = None
            if spec.kind == "crop":
                figure = next((f for f in text.figures if f.figure_id == spec.figure_id), None)
                if figure is None:
                    raise ValueError(f"figure {spec.figure_id} is not in the material")
                page_png = await asyncio.to_thread(p.renderer.page_image, data, mime, figure.page)
            tiles = await asyncio.to_thread(p.renderer.render, spec, page_png)
            preview = await asyncio.to_thread(p.renderer.preview_png, tiles)
            diagram_id = await p.db.save_diagram(doc_id, revision, step.label, spec, tiles, preview)
        except Exception as exc:  # noqa: BLE001 - a diagram failure fails the step, not the job
            log.warning("diagram for step %s not rendered: %s", step.label, type(exc).__name__)
            reason = f"diagram could not be rendered ({str(exc)[:120] or type(exc).__name__}); detach it"
            merged = "; ".join(r for r in (step.verify.reason, reason) if r)
            return step.model_copy(update={"verify": VerifyResult(ok=False, reason=merged)})
        return step.model_copy(update={"diagram_id": diagram_id, "diagram_approved": False})

    async def _fail(self, material_id: str, message: str) -> None:
        try:
            await self.p.db.set_material_status(material_id, "failed", message)
        except Exception as exc:  # noqa: BLE001
            log.error("could not mark %s failed: %s", material_id, type(exc).__name__)

    async def shutdown(self) -> None:
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
