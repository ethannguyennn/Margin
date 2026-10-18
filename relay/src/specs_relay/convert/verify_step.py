"""Deterministic draft-step verifier. No LLM.

A converted step passes only if all of these hold:

1. it has quotes, and every quote appears in the MaterialText (v1 normalisation,
   fuzzy >= 0.95 with identical digits) and quotes no ``[illegible]`` or
   failed-page marker;
2. every number+unit token and part code in glance, body, warning, checkpoint,
   diagram caption and schematic labels appears in one of the step's own
   quotes (v1 tokeniser, exact token match; the step label may appear bare);
3. a warning is the material's own warning, shortened only by deletion, and
   never by deleting a negation ("Do not lubricate" -> "Lubricate");
4. caps hold after ``sanitize()``;
5. a crop names an existing figure with a non-degenerate bbox inside 0..1;
   a schematic has 1-40 elements and labels of at most 12 chars.

Every failure is a sentence a supervisor can act on in the portal, e.g.
"body says 5 N-m; no quote contains 5 N-m". Inputs may be pydantic models or
plain dicts, so the matrix runs against hand-written MaterialText.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from ..pipeline.sanitize import sanitize
from ..schemas import STEP_CHECKPOINT_MAX, STEP_WARNING_MAX
from ..pipeline.verify import BODY_MAX, GLANCE_MAX, _get, iter_number_tokens, normalize, quote_in_text

# Limits for new steps, tighter than the contract ceilings (see schemas.py).
WARNING_MAX = STEP_WARNING_MAX
CHECKPOINT_MAX = STEP_CHECKPOINT_MAX
ALT_MAX = 80
LABEL_MAX = 12
ELEMENTS_MAX = 40
MIN_BOX_SIDE = 0.02  # a crop narrower than 2 % of the page is a degenerate box

_NEGATIONS = frozenset({"not", "no", "never", "nor", "without"})
_CONTRACTION = re.compile(r"n['’]t\b", re.I)
_CANNOT = re.compile(r"\bcannot\b", re.I)
_SENTENCE = re.compile(r"(?<=[.!?;:])\s+")
_CALLOUT_NUMBER = re.compile(r"^\d{1,2}$")


def _words(text: str) -> list[str]:
    text = _CANNOT.sub("can not", _CONTRACTION.sub(" not", text))
    return normalize(text).split()


def _material_text(text: Any) -> str:
    pages = sorted(_get(text, "pages") or [], key=lambda p: _get(p, "page") or 0)
    return "\n".join(_get(p, "text") or "" for p in pages)


def _check_quotes(quotes: list[str], material: str, reasons: list[str]) -> list[str]:
    """Reasons for bad quotes; returns the quotes that may support claims."""
    good = []
    for i, quote in enumerate(quotes, start=1):
        words = normalize(quote).split()
        if "illegible" in words:
            reasons.append(f"quote {i} relies on text marked [illegible]")
        elif "failed to read" in " ".join(words):
            reasons.append(f"quote {i} relies on a page that failed to read")
        elif not quote_in_text(quote, material):
            shown = quote if len(quote) <= 60 else quote[:57] + "..."
            reasons.append(f'quote {i} is not in the material: "{shown}"')
        else:
            good.append(quote)
    return good


def _check_values(field: str, text: str, quoted: set[str], allowed_bare: set[str], reasons: list[str]) -> None:
    seen = set()
    for tok, shown in iter_number_tokens(text):
        if tok in seen or tok in quoted or tok in allowed_bare:
            continue
        seen.add(tok)
        reasons.append(f"{field} says {shown}; no quote contains {shown}")


def _subsequence(needle: list[str], hay: list[str]) -> tuple[int, int] | None:
    """Greedy match of ``needle`` as an in-order subsequence of ``hay``: (first, last) index."""
    if not needle:
        return None
    first, j = -1, 0
    for i, w in enumerate(hay):
        if w == needle[j]:
            if j == 0:
                first = i
            j += 1
            if j == len(needle):
                return first, i
    return None


def _warning_failure(warning: str, quotes: list[str]) -> str | None:
    wanted = _words(warning)
    wanted_neg = Counter(w for w in wanted if w in _NEGATIONS)
    dropped: str | None = None
    for quote in quotes:
        # Word list per sentence, so negations around the match are in scope.
        sentences = [_words(s) for s in _SENTENCE.split(quote)]
        flat = [w for s in sentences for w in s]
        owner = [k for k, s in enumerate(sentences) for _ in s]
        hit = _subsequence(wanted, flat)
        if hit is None:
            continue
        region = [w for k in range(owner[hit[0]], owner[hit[1]] + 1) for w in sentences[k]]
        lost = Counter(w for w in region if w in _NEGATIONS) - wanted_neg
        if not lost:
            return None
        dropped = sorted(lost)[0]
    if dropped:
        return f"warning drops '{dropped}' from the material's warning"
    return "warning is not the material's own warning text"


def _box_failure(bbox: Any) -> str | None:
    if bbox is None:
        return "diagram crop box is missing"
    try:
        x0, y0, x1, y1 = (float(v) for v in bbox)
    except (TypeError, ValueError):
        return "diagram crop box is not four numbers"
    shown = f"({x0:g}, {y0:g}, {x1:g}, {y1:g})"
    if min(x0, y0, x1, y1) < 0 or max(x0, y0, x1, y1) > 1:
        return f"diagram crop box {shown} is outside the page (0..1)"
    if x1 - x0 < MIN_BOX_SIDE or y1 - y0 < MIN_BOX_SIDE:
        return f"diagram crop box {shown} is empty or inverted"
    return None


def _check_diagram(spec: Any, text: Any, quoted: set[str], reasons: list[str]) -> None:
    kind = _get(spec, "kind")
    alt = sanitize(_get(spec, "alt") or "")
    if len(alt) > ALT_MAX:
        reasons.append(f"diagram caption is {len(alt)} chars; the limit is {ALT_MAX}")
    _check_values("diagram caption", alt, quoted, set(), reasons)
    if kind == "crop":
        figures = {_get(f, "figure_id") for f in _get(text, "figures") or []}
        fid = _get(spec, "figure_id")
        if fid not in figures:
            reasons.append(f"diagram crops figure {fid}, which is not in the material")
        box = _box_failure(_get(spec, "bbox"))
        if box:
            reasons.append(box)
    elif kind == "schematic":
        elements = list(_get(spec, "elements") or [])
        if not elements:
            reasons.append("diagram schematic has no elements")
        if len(elements) > ELEMENTS_MAX:
            reasons.append(f"diagram has {len(elements)} elements; the limit is {ELEMENTS_MAX}")
        for el in elements:
            label = _get(el, "label")
            if not label:
                continue
            shown = sanitize(label)
            if len(shown) > LABEL_MAX:
                reasons.append(f"diagram label '{shown}' is {len(shown)} chars; the limit is {LABEL_MAX}")
            # Numbered callouts are sequence markers (1, 2, 3...), not material values.
            if _get(el, "type") == "callout" and _CALLOUT_NUMBER.match(shown.strip()):
                continue
            _check_values("diagram label", shown, quoted, set(), reasons)
    else:
        reasons.append(f"diagram kind '{kind}' is not crop or schematic")


def step_failures(step: Any, text: Any) -> list[str]:
    """Every reason ``step`` fails against ``text`` (empty list = passes)."""
    reasons: list[str] = []
    quotes = [q for q in (_get(step, "quotes") or []) if isinstance(q, str)]
    if not quotes:
        reasons.append("no quotes: every step needs source quotes")
    good = _check_quotes(quotes, _material_text(text), reasons)
    quoted: set[str] = set()
    for q in good:
        quoted |= {tok for tok, _ in iter_number_tokens(q)}

    label = str(_get(step, "label") or "").strip()
    bare_label = {f"{label}|"} if label else set()
    fields = [
        ("glance", _get(step, "glance") or "", GLANCE_MAX),
        ("body", _get(step, "body") or "", BODY_MAX),
        ("warning", _get(step, "warning"), WARNING_MAX),
        ("checkpoint", _get(step, "checkpoint"), CHECKPOINT_MAX),
    ]
    for name, raw, cap in fields:
        if raw is None:
            continue
        shown = sanitize(raw)
        if name == "glance" and not shown.strip():
            reasons.append("glance is empty")
        if len(shown) > cap:
            reasons.append(f"{name} is {len(shown)} chars; the lens limit is {cap}")
        if good:  # with no usable quote, that is the one reason worth reading
            _check_values(name, shown, quoted, bare_label, reasons)

    warning = _get(step, "warning")
    if warning:
        failure = _warning_failure(warning, good)
        if failure:
            reasons.append(failure)

    spec = _get(step, "diagram")
    if spec is not None:
        _check_diagram(spec, text, quoted, reasons)
    return reasons


def verify_step(step: Any, text: Any):
    """Protocol entry point: v1's ``VerifyResult``; ``reason`` joins every failure."""
    from ..schemas import VerifyResult

    reasons = step_failures(step, text)
    return VerifyResult(ok=not reasons, reason="; ".join(reasons) or None, citations=[])
