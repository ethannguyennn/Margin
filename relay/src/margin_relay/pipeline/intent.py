"""Rule-based intent classifier. No LLM, sub-millisecond.

First match wins: command (v2), walkthrough, deviation, repeat, else question.
An empty transcript is ``unknown``.

Commands (BUILD-PLAN-V2 section 3) and v1 ``repeat`` must be the whole
utterance once filler words are stripped, so "what's the next step's torque"
and "what was that torque spec" stay questions. "repeat the warning about
power" is a question too: retrieval answers it from the warning chunk.
"""

from __future__ import annotations

import re

# BUILD-PLAN-V2 section 3, verbatim. Whole-utterance matches only.
COMMAND_PHRASES: dict[str, tuple[str, ...]] = {
    "next": ("next", "done", "next step", "finished", "complete"),
    "back": ("back", "previous", "go back"),
    "repeat": ("repeat", "say that again"),
    "details": ("details", "more", "read it"),
    "diagram": ("diagram", "show diagram", "picture", "show me"),
    "pause": ("pause", "stop task"),
    "resume": ("resume", "continue"),
    "exit": ("exit", "close margin"),
}
_PHRASE_TO_COMMAND = {p: c for c, ps in COMMAND_PHRASES.items() for p in ps}
_FILLER = frozenset({"ok", "okay", "um", "uh", "please", "margin", "hey"})
_WORD = re.compile(r"[a-z]+")


def parse_command(transcript: str | None) -> str | None:
    """The ``Command`` if the whole utterance is one, else None.

    Filler words are stripped from both ends one at a time and every
    intermediate form is tried, so "close margin" keeps its "margin" while
    "hey margin, next please" still reads as "next".
    """
    words = _WORD.findall((transcript or "").lower())
    lo, hi = 0, len(words)
    while lo < hi:
        hit = _PHRASE_TO_COMMAND.get(" ".join(words[lo:hi]))
        if hit:
            return hit
        if words[lo] in _FILLER:
            lo += 1
        elif words[hi - 1] in _FILLER:
            hi -= 1
        else:
            return None
    return None

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
    """Return one of ``command | question | walkthrough | deviation | repeat | unknown``."""
    t = (transcript or "").strip()
    if not _HAS_WORD.search(t):
        return "unknown"
    if parse_command(t):
        return "command"
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
