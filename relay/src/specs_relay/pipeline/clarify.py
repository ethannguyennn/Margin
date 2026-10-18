"""v3 clarify: ask the worker "which one?" and resolve the reply (BUILD-PLAN-V3 section 2).

Options are never generated prose. Each one is quoted from approved text that retrieval
returned for this question:

- the *subject* of a section heading: the words before ":" or before "specifications"
  ("Latte: add syrup" -> "Latte", "Cappuccino specifications" -> "Cappuccino"), or the
  whole heading when it has neither; or
- a document title, when the retrieved sections span documents and the top document
  alone does not offer two choices.

``grounded`` re-checks every option against the chunks deterministically, the way the
verifier checks a quote. Fewer than two grounded options -> no clarify (NOT_FOUND).
"""

from __future__ import annotations

import re
from typing import Any, Callable

from ..schemas import (CLARIFY_OPTION_MAX, CLARIFY_OPTIONS_MAX, CLARIFY_OPTIONS_MIN, Chunk,
                       Clarify)

PROMPT_SECTION = "Which one?"
PROMPT_DOCUMENT = "Which procedure?"

_SUBJECT = re.compile(r"^(?P<subject>.+?)\s*(?::\s*.*|\s+specifications?)$", re.IGNORECASE)
_WORDS = re.compile(r"[a-z0-9]+")
# A reply this short is an answer to "which one?", not a new question.
REPLY_MAX_WORDS = 4
# A reply naming an option still resolves up to this length ("the iced latte for a large");
# past it, it is a new question even if it mentions one ("how long do I steam ... cappuccino").
NAMED_REPLY_MAX_WORDS = 8
_FILLER = frozenset({"the", "a", "an", "one", "for", "um", "uh", "ok", "okay", "please", "i", "mean",
                     "meant", "it", "is", "its", "it's", "that"})


def subject(heading: str) -> str:
    """The thing a section is about: "Latte: add syrup" -> "Latte"."""
    heading = heading.strip()
    m = _SUBJECT.match(heading)
    return (m.group("subject") if m else heading).strip()


def _has_subject_form(heading: str | None) -> bool:
    return bool(heading and _SUBJECT.match(heading.strip()))


def _ok(option: str) -> bool:
    return 0 < len(option) <= CLARIFY_OPTION_MAX and option.isascii() and option.isprintable()


def _distinct(values: list[str]) -> list[str]:
    out: list[str] = []
    for v in values:
        if _ok(v) and v.lower() not in {o.lower() for o in out}:
            out.append(v)
    return out


def grounded(option: str, chunks: list[Chunk]) -> bool:
    """True iff ``option`` is the subject of a retrieved heading or a retrieved title."""
    low = option.lower()
    return any((c.heading and subject(c.heading).lower() == low) or (c.title and c.title.lower() == low)
               for c in chunks)


def build_clarify(chunks: list[Chunk], sanitize: Callable[[str], str]) -> Clarify | None:
    """2-3 grounded options in retrieval order, or None. ``chunks`` are best first."""
    if not chunks:
        return None
    clean = lambda s: sanitize(s).strip()  # noqa: E731
    top_doc = chunks[0].doc_id
    sections = _distinct([clean(subject(c.heading)) for c in chunks
                          if c.doc_id == top_doc and c.heading])
    if len(sections) >= CLARIFY_OPTIONS_MIN:
        options, prompt = sections, PROMPT_SECTION
    else:
        titles = _distinct([clean(c.title) for c in chunks if c.title])
        options, prompt = titles, PROMPT_DOCUMENT
    options = [o for o in options if grounded(o, chunks)][:CLARIFY_OPTIONS_MAX]
    if len(options) < CLARIFY_OPTIONS_MIN:
        return None
    return Clarify(prompt=prompt, options=options)


def _words(text: str) -> list[str]:
    return _WORDS.findall(text.lower())


def resolves(clarify: Clarify | None, reply: str) -> bool:
    """Is ``reply`` the worker's answer to ``clarify``? It names an option, or it is a
    short reply (a few words). A long reply naming no option is a new question."""
    if clarify is None or not reply.strip():
        return False
    words = _words(reply)
    said = " ".join(words)
    named = any(" ".join(_words(o)) and f" {' '.join(_words(o))} " in f" {said} " for o in clarify.options)
    if named and len(words) <= NAMED_REPLY_MAX_WORDS:
        return True
    content = [w for w in words if w not in _FILLER]
    return 0 < len(content) <= REPLY_MAX_WORDS and len(words) <= REPLY_MAX_WORDS + 2


def combined_question(previous_question: str, reply: str) -> str:
    """The question to retrieve and answer once a reply resolves a clarify."""
    q = previous_question.strip()
    return f"{q}{'' if q.endswith(('?', '.', '!')) else '?'} {reply.strip()}"


def names_a_subject(query: str, chunks: list[Any]) -> bool:
    """Mock helper: does the question already name one of the sections' subjects?"""
    said = f" {' '.join(_words(query))} "
    return any(f" {' '.join(_words(subject(c.heading)))} " in said
               for c in chunks if _has_subject_form(getattr(c, "heading", None)))
