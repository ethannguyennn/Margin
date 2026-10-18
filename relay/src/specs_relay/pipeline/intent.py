"""Rule-based intent classifier. No LLM, sub-millisecond.

First match wins: command (v2), walkthrough, deviation, repeat, else question.
An empty transcript is ``unknown``.

Commands (BUILD-PLAN-V2 section 3) and v1 ``repeat`` must be the whole
utterance once filler words are stripped, so "what's the next step's torque"
and "what was that torque spec" stay questions. "repeat the warning about
power" is a question too: retrieval answers it from the warning chunk.
Natural phrasing of a command is the fallback (``_loose_command``).
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
    "exit": ("exit", "close specs"),
}
_PHRASE_TO_COMMAND = {p: c for c, ps in COMMAND_PHRASES.items() for p in ps}
_FILLER = frozenset({"ok", "okay", "um", "uh", "please", "specs", "hey"})
_WORD = re.compile(r"[a-z]+")


def parse_command(transcript: str | None) -> str | None:
    """The ``Command`` if the whole utterance is one, else None.

    Filler words are stripped from both ends one at a time and every
    intermediate form is tried, so "close specs" keeps its "specs" while
    "hey specs, next please" still reads as "next". Natural phrasing falls
    through to ``_loose_command``.
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
            break
    return _loose_command(transcript) if words else None


# Natural phrasing: workers don't recite the phrase table. Every word must be filler or a
# command word, all naming one command, with no question word or number, so "go to the
# next step" and "I'm done" are commands while "back off the gland nut" stays a question.
_COMMAND_WORDS: dict[str, str] = {
    **dict.fromkeys(("next", "done", "finished", "finish", "complete", "completed", "forward",
                     "onward", "skip", "move", "ahead", "got"), "next"),
    **dict.fromkeys(("back", "previous", "backward", "backwards", "last"), "back"),
    **dict.fromkeys(("repeat", "again"), "repeat"),
    **dict.fromkeys(("details", "detail", "more", "explain", "expand", "info", "tell", "read"), "details"),
    **dict.fromkeys(("diagram", "picture", "image", "drawing", "photo", "see"), "diagram"),
    **dict.fromkeys(("pause", "stop", "hold", "wait", "break"), "pause"),
    **dict.fromkeys(("resume", "continue", "start", "begin", "keep", "going", "carry", "ready"), "resume"),
    **dict.fromkeys(("exit", "quit", "close"), "exit"),
}
_SOFT_FILLER = _FILLER | frozenset(
    "i we let us can could would will you go to the a an this that it its one now just so then "
    "and alright all right yeah yes yep sure thanks thank step task me with on up out show take "
    "give say app".split()
)
_QUESTION_WORDS = frozenset("what how why where when which who whose is are was were does do did should".split())
_TOKEN = re.compile(r"[a-z']+|\d")


def _loose_command(transcript: str) -> str | None:
    text = transcript.lower().replace("one more time", "again")
    words = [w.split("'")[0] for w in _TOKEN.findall(text)]  # what's -> what, i'm -> i
    if " ".join(words) in ("what next", "what is next"):
        return "next"
    if any(w.isdigit() or w in _QUESTION_WORDS or (w not in _SOFT_FILLER and w not in _COMMAND_WORDS)
           for w in words):
        return None
    keys = [w for w in words if w in _COMMAND_WORDS]
    if "again" in keys:  # "read it again" is a repeat, not details
        keys = [w for w in keys if w != "read"]
    found = {_COMMAND_WORDS[w] for w in keys}
    return found.pop() if len(found) == 1 else None


_WALKTHROUGH = re.compile(
    r"\b(?:guide me|walk (?:me )?through|step by step|take me through|start (?:the )?procedure|"
    r"show me how to|teach me(?: how)? to|what are the steps (?:for|to))\b|"
    r"^(?:open|pull up|bring up|load|start|begin|let['\u2019]s (?:do|start|begin)|i need to (?:do|start|begin))\b"
    r"[^.!?]*\b(?:procedure|checklist|sop|steps|standards|routine|process|opening|closing)\b", re.I
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


def is_picture_request(transcript: str) -> bool:
    return bool(re.search(r"\bwhat does .+ look like\b|^show me (?:the|an?) .+|\bpicture of\b", transcript, re.I))


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
