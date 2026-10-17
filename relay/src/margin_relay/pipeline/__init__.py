"""Pipeline interfaces (owned by Part 3). Part 4 and Part 5 implement them.

Integration contract -- the factory in ``main.py`` loads exactly these names
when ``MOCK_MODE=0`` (each import is lazy; a missing module falls back to the
mock in ``pipeline/mock.py`` with a WARN log and ``/v1/health`` reporting
``mock: true``):

  Part 4  pipeline/transcribe.py  GeminiTranscriber(settings)            -> Transcriber
          pipeline/intent.py      classify_intent(transcript)            -> Intent | IntentResult
          pipeline/retrieve.py    HybridRetriever(settings=..., db=...)  -> Retriever
          pipeline/generate.py    GeminiGenerator(settings)              -> Generator
          pipeline/verify.py      verify(draft, chunks)                  -> VerifyResult
          pipeline/sanitize.py    sanitize(text)                         -> str
  Part 5  db.py                   module with init_pool, ping, vector_top, fts_top,
                                  steps_for, list_procedures, write_event,
                                  next_deviation_id, insert_deviation (+ optional
                                  close_pool, ingest_corpus)
          notify/console.py       ConsoleNotifier()                      -> Notifier
          notify/photon.py        PhotonNotifier(settings)               -> Notifier

``db`` passed to ``HybridRetriever`` is Part 5's ``db`` module (or the mock
DB), so retrieval calls ``await db.vector_top(...)`` / ``await db.fts_top(...)``
and never opens its own connection.

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

from ..schemas import Chunk, Draft, Intent, IntentResult, RetrievalResult, Step, VerifyResult


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


__all__ = [
    "BadRequest",
    "DbDown",
    "Generator",
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
