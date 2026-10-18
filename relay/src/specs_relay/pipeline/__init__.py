"""Pipeline interfaces (owned by Part 3). Part 4 and Part 5 implement them.

Integration contract -- the factory in ``main.py`` loads exactly these names
when ``MOCK_MODE=0`` (each import is lazy; a missing module falls back to the
mock in ``pipeline/mock.py`` with a WARN log and ``/v1/health`` reporting
``mock: true``):

  Part 4  pipeline/transcribe.py  GeminiTranscriber.from_settings(settings, client=) -> Transcriber
          pipeline/intent.py      classify_intent(t) -> Intent, deviation_text(t),
                                  parse_command(t) -> Command | None    (v2)
          pipeline/retrieve.py    Retriever(db.RetrievalStore(), GeminiEmbedder(...))
          pipeline/generate.py    GeminiGenerator.from_settings(settings, client=)    -> Generator
          pipeline/verify.py      verify(draft, chunks)                  -> VerifyResult
          pipeline/sanitize.py    sanitize(text)                         -> str
          convert/structure.py    GeminiConverter.from_settings(settings, client=)    -> Converter  (v2)
          convert/verify_step.py  verify_step(step, material_text)       -> VerifyResult (v2)
          diagrams/render.py      DiagramRenderer()                      -> DiagramRenderer (v2)
  Part 5  db.py                   v1 queries + every v2 query (materials, drafts,
                                  diagrams, devices, assignments, progress)
          walkthrough.py          build_walkthrough, log_deviation, publish_draft (v2)
          notify/__init__.py      get_notifier(settings)                 -> Notifier

Retrieval goes through Part 5's ``db.RetrievalStore``, so it never opens its
own connection. Every v2 route and the conversion job (``jobs.py``) call
Part 5's ``db`` functions; nobody else runs SQL.

Errors: raise the typed errors below. ``/v1/ask`` maps them to the contract
error codes. Anything else raised by a stage is mapped by stage (stt ->
stt_failed, retrieve -> db_down, generate -> llm_timeout).

Timing: ``/v1/ask`` wraps every stage in ``obs.stage(name)``. If you do a
sub-stage inside your module (the embedding call inside ``retrieve``), wrap it
in ``with obs.stage("embed"):`` and it is recorded as its own span and
subtracted from the enclosing stage's ``latency_ms``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..schemas import (
    Chunk,
    Command,
    DiagramSpec,
    Draft,
    DraftStep,
    Intent,
    IntentResult,
    MaterialText,
    ProcedureDraft,
    RetrievalResult,
    Step,
    VerifyResult,
)


class PipelineError(Exception):
    code = "internal"

    def __init__(self, message: str = "") -> None:
        super().__init__(message or self.__class__.__name__)
        self.message = message or self.__class__.__name__


class SttFailed(PipelineError):
    code = "stt_failed"


class LlmTimeout(PipelineError):
    code = "llm_timeout"


class DbDown(PipelineError):
    code = "db_down"


class BadRequest(PipelineError):
    code = "bad_request"


@runtime_checkable
class Transcriber(Protocol):
    async def transcribe(self, pcm: bytes, sample_rate: int) -> str: ...


class IntentClassifier(Protocol):
    def __call__(self, transcript: str) -> Intent | IntentResult: ...


@runtime_checkable
class Retriever(Protocol):
    async def retrieve(self, query: str, revision: str | None) -> RetrievalResult: ...

    async def steps_for(self, doc_id: str, revision: str | None) -> list[Step]: ...


@runtime_checkable
class Generator(Protocol):
    async def generate(
        self, query: str, chunks: list[Chunk], feedback: str | None = None
    ) -> Draft:
        """`feedback` is the verifier's failure reason on the single retry, else None."""
        ...


class Verifier(Protocol):
    def __call__(self, draft: Draft, chunks: list[Chunk]) -> VerifyResult: ...


class Sanitizer(Protocol):
    def __call__(self, text: str) -> str: ...


@runtime_checkable
class Notifier(Protocol):
    async def notify(self, deviation_id: str, text: str) -> bool: ...


# --- v2 (BUILD-PLAN-V2 section 5) -------------------------------------------------


class ConversionError(PipelineError):
    """A conversion stage failed; ``message`` is shown to the supervisor verbatim."""

    code = "internal"


class CommandParser(Protocol):
    def __call__(self, transcript: str) -> Command | None:
        """Whole-utterance match only: "next" is a command, "what's the next step" is not."""
        ...


@runtime_checkable
class Converter(Protocol):
    async def extract(self, data: bytes, mime: str, material_id: str) -> MaterialText: ...

    async def convert(self, text: MaterialText, doc_id: str, revision: str,
                      title: str) -> ProcedureDraft: ...


class StepVerifier(Protocol):
    def __call__(self, step: DraftStep, text: MaterialText) -> VerifyResult:
        """Deterministic, no LLM: quotes in the material, values in the quotes, caps."""
        ...


@runtime_checkable
class DiagramRenderer(Protocol):
    def render(self, spec: DiagramSpec, page_image: bytes | None) -> list[bytes]:
        """1-2 tiles (slot 0 left, slot 1 right) in the lens byte format."""
        ...

    def preview_png(self, tiles: list[bytes]) -> bytes:
        """576x144 PNG that looks exactly like the lens, for the portal."""
        ...

    def page_image(self, data: bytes, mime: str, page: int) -> bytes:
        """PNG of one (1-based) page of the material, for crops."""
        ...


__all__ = [
    "BadRequest",
    "CommandParser",
    "ConversionError",
    "Converter",
    "DbDown",
    "DiagramRenderer",
    "Generator",
    "StepVerifier",
    "IntentClassifier",
    "LlmTimeout",
    "Notifier",
    "PipelineError",
    "Retriever",
    "Sanitizer",
    "SttFailed",
    "Transcriber",
    "Verifier",
]
