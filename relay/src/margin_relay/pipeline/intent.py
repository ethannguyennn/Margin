"""Rule-based intent classifier. No LLM, sub-millisecond.

Case-insensitive regex on the transcript, first match wins:
walkthrough, deviation, repeat, else question. An empty transcript is
``unknown``.

``repeat`` must be the whole utterance (plus filler words), so "what was that
torque spec" stays a question.
"""

from __future__ import annotations

import re

_WALKTHROUGH = re.compile(
    r"\b(?:guide me|walk me through|step by step|take me through|start procedure)\b", re.I
)
# README pattern is `report (an )?(...)`; `an?` also accepts "report a problem".
_DEVIATION = re.compile(
    r"\b(?:log (?:a )?deviation|report (?:an? )?(?:issue|problem|nonconformance)|flag this)\b", re.I
)
_REPEAT = re.compile(
    r"^(?:(?:ok(?:ay)?|sorry|hey|please|can you|could you)[\s,]*)*"
    r"(?:repeat(?: that| it)?|say that again|what was that)"
    r"(?:[\s,]+(?:please|again))*[\s?.!]*$",
    re.I,
)
_HAS_WORD = re.compile(r"\w")
_DEVIATION_LEAD = re.compile(r"^[\s:;,.\-]*(?:that\b)?[\s:;,\-]*", re.I)


def classify_intent(transcript: str | None) -> str:
    """Return one of ``question | walkthrough | deviation | repeat | unknown``."""
    t = (transcript or "").strip()
    if not _HAS_WORD.search(t):
        return "unknown"
    if _WALKTHROUGH.search(t):
        return "walkthrough"
    if _DEVIATION.search(t):
        return "deviation"
    if _REPEAT.match(t):
        return "repeat"
    return "question"


def deviation_text(transcript: str | None) -> str:
    """The transcript with the deviation trigger phrase stripped: what gets logged."""
    t = (transcript or "").strip()
    m = _DEVIATION.search(t)
    if not m:
        return t
    before = t[: m.start()].strip()
    after = _DEVIATION_LEAD.sub("", t[m.end():], count=1).strip()
    return " ".join(p for p in (before, after) if p)
