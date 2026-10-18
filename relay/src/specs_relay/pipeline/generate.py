"""Grounded generation: one structured-output Gemini call over the retrieved
chunks, and the question path that wraps it in the verifier.

``answer_question`` is the whole trust layer in one place:

    retrieve -> gate (not_found, no LLM) -> generate -> verify
             -> on failure: generate once more with the reason -> verify
             -> on failure: not_found.  Unverified text is never returned.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from ..schemas import NOT_FOUND_BODY, NOT_FOUND_GLANCE
from . import LlmTimeout
from .retrieve import should_refuse
from .sanitize import sanitize
from .verify import BODY_MAX, GLANCE_MAX, check_draft

GENERATE_TIMEOUT_S = 20.0
TEMPERATURE = 0.1

SYSTEM_PROMPT = f"""\
You answer questions about company procedures using ONLY the provided CONTEXT chunks.
The answer is read on smart glasses mid-task: use as few words as possible.
Rules:
1. If the context does not contain the answer, return answerable=false. Never guess.
2. Every claim must be supported by a verbatim quote copied from a chunk. Cite chunk_id and quote.
   Copy the quote character for character; do not paraphrase inside a quote.
   For short instructions, cite the whole source instruction so all stated values remain supported.
3. glance: <= {GLANCE_MAX} characters, ASCII only. Verb + object + value, no articles or filler.
   Example: "Torque M5 to 4 N-m".
4. body: <= {BODY_MAX} characters, ASCII only, at most 2 short sentences, no markdown. Only what
   the glance leaves out (a warning, an order, a check). Empty when the glance is enough.
5. Never restate the question, never address the reader ("you should"), and never name the
   document or section in glance or body: the source is shown separately.
6. Preserve numbers, units, and warnings exactly as written. Never convert units.
   Every number and part code in glance or body must appear in one of your quotes.
7. If the question is ambiguous between procedures, answerable=false and needs_clarification=true.
8. Choose graphic_id from AVAILABLE GRAPHICS only when its reference anchor occurs in a quote you cite.
   Choose the most useful equipment view for this instruction; otherwise return null. Never invent a URL.
9. Count every character in glance, including spaces: at most {GLANCE_MAX}. Copy numbers with
   their units exactly from the quote. Preserve inner quotation marks and degree/unit glyphs
   in citations; JSON-escape quotation marks rather than rewriting or shortening the quote.
Return JSON: {{answerable, needs_clarification, glance, body, citations:[{{chunk_id, quote}}], graphic_id}}
When answerable=false, return empty glance, body and citations."""

RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "graphic_id": {"type": ["string", "null"]},
        "answerable": {"type": "boolean"},
        "needs_clarification": {"type": "boolean"},
        "glance": {"type": "string"},
        "body": {"type": "string"},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"chunk_id": {"type": "string"}, "quote": {"type": "string"}},
                "required": ["chunk_id", "quote"],
            },
        },
    },
    "required": ["answerable", "needs_clarification", "glance", "body", "citations", "graphic_id"],
}


class GenerationError(LlmTimeout):
    """Unusable model output (bad JSON, schema mismatch, API error)."""


class GenerationTimeout(GenerationError):
    pass


class GenerationUnavailable(GenerationError):
    """Gemini said "not now" (429 quota, 5xx overload): worth one retry after a short
    pause, but not with feedback to the model -- its last answer was not the problem."""

    transient = True


# HTTP codes from the Gemini API that mean "try again shortly", not "your request is bad".
TRANSIENT_CODES = frozenset({429, 500, 503, 504})


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def secret(value: Any) -> str:
    """Plain string from a str or pydantic ``SecretStr``."""
    return value.get_secret_value() if hasattr(value, "get_secret_value") else (value or "")


def gemini_client(api_key: Any):
    from google import genai

    key = secret(api_key)
    if not key:
        raise ValueError("GEMINI_API_KEY is not set")
    return genai.Client(api_key=key)


def build_prompt(query: str, chunks: list[Any], feedback: str | None = None) -> str:
    parts = ["CONTEXT:"]
    for c in chunks:
        head = f"{_get(c, 'doc_id')} rev {_get(c, 'revision')} Sec {_get(c, 'section')}"
        if _get(c, "heading"):
            head += f" - {_get(c, 'heading')}"
        parts.append(f"[chunk_id: {_get(c, 'chunk_id')}] {head}\n{_get(c, 'text')}\n")
    from ..illustrations import available_graphics
    parts.append("AVAILABLE GRAPHICS: " + json.dumps(available_graphics(chunks)))
    parts.append(f"QUESTION: {query}")
    if feedback:
        parts.append(
            "\nYOUR PREVIOUS ANSWER WAS REJECTED by the citation verifier: "
            f"{feedback}\nFix it using only verbatim quotes, or return answerable=false."
        )
    return "\n".join(parts)


def parse_draft(text: str):
    from ..schemas import Draft

    try:
        data = json.loads(text)
        return Draft.model_validate(data)
    except Exception as e:
        raise GenerationError(f"malformed model output: {type(e).__name__}") from e


class GeminiGenerator:
    def __init__(self, client: Any, model: str, temperature: float = TEMPERATURE,
                 timeout: float = GENERATE_TIMEOUT_S):
        if not model:
            raise ValueError("GEMINI_MODEL_GENERATE is not set")
        self.client, self.model, self.temperature, self.timeout = client, model, temperature, timeout
        self.calls = 0

    @classmethod
    def from_settings(cls, settings: Any, client: Any = None) -> "GeminiGenerator":
        # Shared with the route's guard (GENERATE_TIMEOUT_S); the route also caps each
        # attempt by the ask budget left (ASK_BUDGET_S).
        return cls(client or gemini_client(settings.gemini_api_key), settings.gemini_model_generate,
                   timeout=getattr(settings, "generate_timeout_s", GENERATE_TIMEOUT_S))

    async def generate(self, query: str, chunks: list[Any], feedback: str | None = None):
        from google.genai import types

        self.calls += 1
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=self.temperature,
            response_mime_type="application/json",
            response_json_schema=RESPONSE_SCHEMA,
        )
        try:
            resp = await asyncio.wait_for(
                self.client.aio.models.generate_content(
                    model=self.model, contents=build_prompt(query, chunks, feedback), config=config
                ),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError as e:
            raise GenerationTimeout("generation timed out") from e
        except Exception as e:  # never echo the prompt or key
            code = getattr(e, "code", None)
            if code in TRANSIENT_CODES:
                raise GenerationUnavailable(f"generation unavailable: HTTP {code}") from e
            raise GenerationError(f"generation failed: {type(e).__name__}") from e
        return parse_draft(resp.text or "")


@dataclass
class GroundedAnswer:
    """What the question path hands back to ``/v1/ask``."""

    outcome: str                      # answered | not_found | clarify
    glance: str = NOT_FOUND_GLANCE
    body: str = NOT_FOUND_BODY
    source: str = ""
    citations: list = field(default_factory=list)   # schemas.Citation
    verified: bool = False
    graphic_id: str | None = None
    llm_calls: int = 0
    reasons: list[str] = field(default_factory=list)  # verifier failures, for logs/eval
    retrieval: Any = None


async def answer_question(query: str, retriever: Any, generator: Any, *, revision: str | None,
                          min_sim: float, min_rrf: float, retrieval: Any = None) -> GroundedAnswer:
    """The question branch of ``/v1/ask``. ``GenerationTimeout`` propagates
    (``llm_timeout``); every other failure degrades to ``not_found``."""
    from ..schemas import Citation

    result = retrieval or await retriever.retrieve(query, revision)
    if not result.chunks or should_refuse(result.best_sim, result.best_rrf, min_sim, min_rrf):
        return GroundedAnswer(outcome="not_found", retrieval=result)

    answer = GroundedAnswer(outcome="not_found", retrieval=result)
    feedback = None
    for _ in range(2):
        answer.llm_calls += 1
        try:
            draft = await generator.generate(query, result.chunks, feedback=feedback)
        except GenerationTimeout:
            raise
        except GenerationError as e:
            feedback = f"malformed_output: {e}. Return JSON matching the schema."
            answer.reasons.append(feedback)
            continue
        if not _get(draft, "answerable") or _get(draft, "needs_clarification"):
            # The model refusing is a success state, not something to retry.
            answer.outcome = "clarify" if _get(draft, "needs_clarification") else "not_found"
            return answer
        reason, cites = check_draft(draft, result.chunks)
        if reason is None:
            first = cites[0]
            return GroundedAnswer(
                outcome="answered",
                glance=sanitize(_get(draft, "glance")).strip(),
                body=sanitize(_get(draft, "body")).strip(),
                source=f"{first['doc_id']} Sec {first['section']} rev {first['revision']}",
                citations=[Citation(**c) for c in cites],
                verified=True,
                graphic_id=_get(draft, "graphic_id"),
                llm_calls=answer.llm_calls,
                reasons=answer.reasons,
                retrieval=result,
            )
        answer.reasons.append(reason)
        feedback = reason
    return answer
