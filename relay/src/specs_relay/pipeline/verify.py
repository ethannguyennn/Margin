"""Deterministic citation verifier. No LLM: this is the trust layer.

A draft passes only if all of these hold:

1. it is answerable, has at least one citation, and fits the lens caps;
2. every cited ``chunk_id`` is in the retrieved set;
3. every quote appears in its chunk after normalization (case, whitespace,
   punctuation), or matches a same-length window at a ``difflib`` ratio
   >= 0.95 *with exactly the same digits* -- fuzziness tolerates spacing noise,
   never a changed value;
4. every number+unit token and part code (``4 N-m``, ``M5``, ``SOP-131``) in
   ``glance`` or ``body`` appears in at least one cited quote, with the same
   unit (or the same absence of one). A bare number may also be a cited
   section label ("Step 4.2").

Inputs may be pydantic models or plain dicts, so the matrix in
``tests/test_verify.py`` runs against hand-written chunks.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from html import unescape
from typing import Any, Iterator

from ..schemas import ANSWER_BODY_MAX, ANSWER_GLANCE_MAX
from .sanitize import sanitize

# Limits for new text, tighter than the contract ceilings (see schemas.py).
GLANCE_MAX = ANSWER_GLANCE_MAX
BODY_MAX = ANSWER_BODY_MAX
FUZZY_MIN_RATIO = 0.95
FUZZY_MIN_LEN = 12  # shorter quotes must match exactly

_NON_ALNUM = re.compile(r"[^0-9a-z-]+")  # preserve signs; -20 is not 20
_DIGITS = re.compile(r"\d+")
# Part codes: M5, HX-2, SOP-131, M5x0.8 is out of scope.
_CODE = re.compile(r"\b[a-z]{1,4}-?\d+(?:\.\d+)?[a-z]?\b")
# Units after a number. Deliberately omits bare "in", "a" and "x", which are
# far more often English words than units ("4 in a star pattern").
_UNIT = (
    r"n-m|n\s?m|in-lbs?|ft-lbs?|lbf|lbs?|kg|mg|g|mm|cm|um|m|ft"
    r"|ms|minutes?|min|seconds?|sec|s|hours?|hrs?|h"
    r"|degrees?\s*(?:fahrenheit|celsius|[cf])|fahrenheit|celsius|deg\s?c|deg\s?f|deg|[cf]|%|psi|bar|kpa|mpa|pa"
    r"|mv|v|ma|kohm|ohm|kw|w|ml|ul|l|rpm|hz|ppm|fl\s?oz|oz|pumps?|inches|inch"
)
_NUMBER = re.compile(rf"(?<![\w.])(-?\d+(?:[.,]\d+)*)(?:\s*({_UNIT}))?(?![a-z0-9])")
_UNIT_ALIASES = {"sec": "s", "hrs": "h", "hr": "h", "lbs": "lb", "inlbs": "inlb", "ftlbs": "ftlb",
                 "second": "s", "seconds": "s", "minute": "min", "minutes": "min", "hour": "h", "hours": "h",
                 "fahrenheit": "degf", "degreefahrenheit": "degf", "degreesfahrenheit": "degf",
                 "celsius": "degc", "degreecelsius": "degc", "degreescelsius": "degc",
                 "degreef": "degf", "degreesf": "degf", "degreec": "degc", "degreesc": "degc",
                 "pumps": "pump", "inches": "inch"}


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def normalize(text: str) -> str:
    """Lowercase, glyphs sanitized, punctuation to spaces, whitespace collapsed."""
    return " ".join(_NON_ALNUM.sub(" ", sanitize(unescape(text)).casefold()).split())


def quote_in_text(quote: str, text: str) -> bool:
    nq, nt = normalize(quote), normalize(text)
    if not nq:
        return False
    if nq in nt:
        return True
    if len(nq) < FUZZY_MIN_LEN:
        return False
    digits = _DIGITS.findall(nq)
    values = tuple(tok for tok, _ in iter_number_tokens(nq))
    slack = max(2, int(len(nq) * (1 - FUZZY_MIN_RATIO)) + 1)
    sm = SequenceMatcher(autojunk=False)
    sm.set_seq2(nq)
    starts = [0] + [i + 1 for i, ch in enumerate(nt) if ch == " "]
    for start in starts:
        for length in range(len(nq) - slack, len(nq) + slack + 1):
            window = nt[start:start + length]
            if len(window) < length:
                break
            sm.set_seq1(window)
            if (
                sm.real_quick_ratio() >= FUZZY_MIN_RATIO
                and sm.quick_ratio() >= FUZZY_MIN_RATIO
                and sm.ratio() >= FUZZY_MIN_RATIO
                and _DIGITS.findall(window) == digits
                and tuple(tok for tok, _ in iter_number_tokens(window)) == values
            ):
                return True
    return False


def iter_number_tokens(text: str) -> Iterator[tuple[str, str]]:
    """``(token, as written)`` for every value in ``text``, e.g. ``("4|nm", "4 N-m")``.

    The spelling is sliced from the sanitized text, so reasons shown to people
    quote the value the way the material or the draft wrote it.
    """
    shown = sanitize(text)
    t = shown.casefold()  # sanitized text is ASCII + box glyphs: same length
    for m in _CODE.finditer(t):
        yield f"code:{m.group(0)}", shown[m.start():m.end()]
    t = _CODE.sub(lambda m: " " * len(m.group(0)), t)  # keep offsets aligned
    for m in _NUMBER.finditer(t):
        num = m.group(1).replace(",", "")
        unit = re.sub(r"[\s-]", "", m.group(2) or "")
        yield f"{num}|{_UNIT_ALIASES.get(unit, unit)}", shown[m.start():m.end()]


def number_tokens(text: str) -> set[str]:
    """``{"4|nm", "70|%", "4.2|", "code:m5", ...}`` for every value in ``text``."""
    return {tok for tok, _ in iter_number_tokens(text)}


def _unsupported(answer: str, quotes: list[str], sections: list[str]) -> str | None:
    quoted = set().union(*(number_tokens(q) for q in quotes)) if quotes else set()
    # Full cited labels only: allowing the prefix "4" of section "4.3" would let
    # any bare 4 through.
    labels = {f"{s}|" for s in sections}
    for tok in sorted(number_tokens(answer)):
        # Exact token match only: a bare count ("4 pulls") never borrows a
        # quoted value that carries a unit ("4 N-m"), and a value never drops
        # its unit. Bare section labels ("Step 4.2") are allowed.
        if tok in quoted or tok in labels:
            continue
        if tok.endswith(("|f", "|c")) and tok[:-1] + "deg" + tok[-1] in quoted:
            continue  # a source with explicit degrees grounds the compact F/C spelling
        return tok.replace("|", " ").strip()
    return None


def check_draft(draft: Any, chunks: list[Any]) -> tuple[str | None, list[dict]]:
    """Pure core of :func:`verify`: ``(failure reason or None, citations)``.

    Reasons start with a stable code (``not_answerable``, ``glance_too_long``,
    ``body_too_long``, ``no_citations``, ``chunk_not_retrieved``,
    ``quote_not_found``, ``unsupported_number``) followed by detail suitable
    for feeding back into a retry prompt.
    """
    if not _get(draft, "answerable") or _get(draft, "needs_clarification"):
        return "not_answerable", []
    glance = sanitize(_get(draft, "glance") or "")
    body = sanitize(_get(draft, "body") or "")
    if not glance.strip():
        return "empty_glance", []
    if len(glance) > GLANCE_MAX:
        return f"glance_too_long: {len(glance)} chars, the limit is {GLANCE_MAX}", []
    if len(body) > BODY_MAX:
        return f"body_too_long: {len(body)} chars, the limit is {BODY_MAX}", []
    cites = list(_get(draft, "citations") or [])
    if not cites:
        return "no_citations", []

    by_id = {_get(c, "chunk_id"): c for c in chunks}
    out: list[dict] = []
    for cite in cites:
        cid, quote = _get(cite, "chunk_id"), unescape(_get(cite, "quote") or "").strip()
        chunk = by_id.get(cid)
        if chunk is None:
            return f"chunk_not_retrieved: {cid} is not one of the provided chunks", []
        source_text = _get(chunk, "text") or ""
        if not quote_in_text(quote, source_text):
            return f"quote_not_found: the quote cited for {cid} is not verbatim in that chunk", []
        if quote not in source_text:
            quote = source_text  # cite stored text when normalization accepted a formatting variant
        out.append({
            "chunk_id": cid,
            "doc_id": _get(chunk, "doc_id"),
            "revision": _get(chunk, "revision"),
            "section": _get(chunk, "section"),
            "quote": quote,
        })

    quotes = [c["quote"] for c in out]
    sections = [c["section"] for c in out]
    for field, text in (("glance", glance), ("body", body)):
        bad = _unsupported(text, quotes, sections)
        if bad:
            return (
                f"unsupported_number: {field} states '{bad}' but no cited quote contains it; "
                "copy values and units exactly as the quote writes them",
                [],
            )
    graphic_id = _get(draft, "graphic_id")
    if graphic_id is not None:
        from ..illustrations import verify_graphic
        if not verify_graphic(graphic_id, out, chunks):
            return "unsupported_graphic: select a cited reference or null", []
    return None, out


def verify(draft: Any, chunks: list[Any]):
    """Protocol entry point: returns Part 3's ``VerifyResult``."""
    from ..schemas import Citation, VerifyResult

    reason, cites = check_draft(draft, chunks)
    if reason is not None:
        return VerifyResult(ok=False, reason=reason, citations=[])
    return VerifyResult(ok=True, reason=None, citations=[Citation(**c) for c in cites])
