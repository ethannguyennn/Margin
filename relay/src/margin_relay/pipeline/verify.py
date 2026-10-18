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
from typing import Any

from .sanitize import sanitize

GLANCE_MAX = 60
BODY_MAX = 450
FUZZY_MIN_RATIO = 0.95
FUZZY_MIN_LEN = 12  # shorter quotes must match exactly

_NON_ALNUM = re.compile(r"[^0-9a-z]+")
_DIGITS = re.compile(r"\d+")
# Part codes: M5, HX-2, SOP-131, M5x0.8 is out of scope.
_CODE = re.compile(r"\b[a-z]{1,4}-?\d+(?:\.\d+)?[a-z]?\b")
# Units after a number. Deliberately omits bare "in", "a" and "x", which are
# far more often English words than units ("4 in a star pattern").
_UNIT = (
    r"n-m|n\s?m|in-lbs?|ft-lbs?|lbf|lbs?|kg|mg|g|mm|cm|um|m|ft"
    r"|ms|min|sec|s|hrs?|h|deg\s?c|deg\s?f|deg|%|psi|bar|kpa|mpa|pa"
    r"|mv|v|ma|kohm|ohm|kw|w|ml|ul|l|rpm|hz|ppm"
)
_NUMBER = re.compile(rf"(?<![\w.])(\d+(?:[.,]\d+)*)(?:\s*({_UNIT}))?(?![a-z0-9])")
_UNIT_ALIASES = {"sec": "s", "hrs": "h", "hr": "h", "lbs": "lb", "inlbs": "inlb", "ftlbs": "ftlb"}


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def normalize(text: str) -> str:
    """Lowercase, glyphs sanitized, punctuation to spaces, whitespace collapsed."""
    return " ".join(_NON_ALNUM.sub(" ", sanitize(text).casefold()).split())


def _display_text(text: str) -> str:
    # Preserve signs and comparisons that punctuation-insensitive quote matching ignores.
    return " ".join(sanitize(text).casefold().split()).rstrip(".!?")


def quote_in_text(quote: str, text: str) -> bool:
    nq, nt = normalize(quote), normalize(text)
    if not nq:
        return False
    if nq in nt:
        return True
    if len(nq) < FUZZY_MIN_LEN:
        return False
    digits = _DIGITS.findall(nq)
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
            ):
                return True
    return False


def number_tokens(text: str) -> set[str]:
    """``{"4|nm", "70|%", "4.2|", "code:m5", ...}`` for every value in ``text``."""
    t = sanitize(text).casefold()
    tokens = {f"code:{m.group(0)}" for m in _CODE.finditer(t)}
    t = _CODE.sub(" ", t)
    for m in _NUMBER.finditer(t):
        num = m.group(1).replace(",", "")
        unit = re.sub(r"[\s-]", "", m.group(2) or "")
        tokens.add(f"{num}|{_UNIT_ALIASES.get(unit, unit)}")
    return tokens


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
        return "glance_too_long", []
    if len(body) > BODY_MAX:
        return "body_too_long", []
    cites = list(_get(draft, "citations") or [])
    if not cites:
        return "no_citations", []

    by_id = {_get(c, "chunk_id"): c for c in chunks}
    out: list[dict] = []
    for cite in cites:
        cid, quote = _get(cite, "chunk_id"), (_get(cite, "quote") or "").strip()
        chunk = by_id.get(cid)
        if chunk is None:
            return f"chunk_not_retrieved: {cid} is not one of the provided chunks", []
        if not quote_in_text(quote, _get(chunk, "text") or ""):
            return f"quote_not_found: the quote cited for {cid} is not verbatim in that chunk", []
        out.append({
            "chunk_id": cid,
            "doc_id": _get(chunk, "doc_id"),
            "revision": _get(chunk, "revision"),
            "section": _get(chunk, "section"),
            "quote": quote,
        })

    quotes = [c["quote"] for c in out]
    graphic_id = _get(draft, "graphic_id")
    if graphic_id is not None:
        from ..illustrations import verify_graphic

        if not verify_graphic(graphic_id, out, chunks):
            return "graphic_not_cited: choose a provided graphic and cite its reference quote, or use null", []
    display = _get(draft, "display")
    if display is not None:
        items = _get(display, "items") or []
        if _get(display, "kind") not in {"answer", "checklist", "warning"} or not 1 <= len(items) <= 4:
            return "invalid_display", []
        for item in items:
            text = sanitize(item).strip()
            if not text or len(text) > 180 or not normalize(text):
                return "invalid_display_item", []
            # Whole source sentences keep an excerpt from dropping "do not" or a condition.
            if not any(
                _display_text(text) in _display_text(cite["quote"]) and
                any(_display_text(text) == _display_text(sentence) for sentence in
                    re.split(r"(?<=[.!?])\s+|\n+", _get(by_id[cite["chunk_id"]], "text")))
                for cite in out
            ):
                return "display_not_cited: copy complete source sentences into items and quotes", []
    sections = [c["section"] for c in out]
    for field, text in (("glance", glance), ("body", body)):
        bad = _unsupported(text, quotes, sections)
        if bad:
            return (
                f"unsupported_number: {field} states '{bad}' but no cited quote contains it; "
                "copy values and units exactly as the quote writes them",
                [],
            )
    return None, out


def verify(draft: Any, chunks: list[Any]):
    """Protocol entry point: returns Part 3's ``VerifyResult``."""
    from ..schemas import Citation, VerifyResult

    reason, cites = check_draft(draft, chunks)
    if reason is not None:
        return VerifyResult(ok=False, reason=reason, citations=[])
    return VerifyResult(ok=True, reason=None, citations=[Citation(**c) for c in cites])
