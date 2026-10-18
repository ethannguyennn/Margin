"""Full worker loop against a live relay, by voice.

  python voice_loop.py prepare   # writes utterances.txt (then run tts.ps1)
  python voice_loop.py run       # sends wav/<n>.wav as pcm_s16le to RELAY, writes results.json
"""
import base64
import json
import sys
import time
import uuid
import wave
from pathlib import Path

import httpx

HERE = Path(__file__).parent
RELAY = "http://127.0.0.1:8090"

# (id, utterance, expectation). ctx is filled in from the walkthrough opened by o3 / o4.
OPEN = [
    ("o1", "walk me through getting the register ready before my shift", "SOP-201"),
    ("o2", "take me through closing out the till at the end of the night", "SOP-202"),
    ("o3", "guide me through the kitchen opening checklist", "SOP-210"),
    ("o4", "show me how to pull a good espresso shot", "SOP-220"),
    ("o5", "walk me through making a cappuccino", "SOP-230"),
    # No walkthrough trigger phrase: how a worker might actually say it.
    ("n1", "I need to do the cash count for closing", "SOP-202"),
    ("n2", "pull up the espresso standards", "SOP-220"),
    ("n3", "open the cleaning procedure", "SOP-210"),
    ("n4", "let's start the back of house opening", "SOP-210"),
    ("x1", "walk me through changing a flat tire", "not_found"),
]
NAV = [  # spoken while on a step of SOP-210
    ("c1", "next", "next"),
    ("c2", "okay I'm done with that one", "next"),
    ("c3", "go back", "back"),
    ("c4", "what's next", "next"),
    ("c5", "say that again", "repeat"),
    ("c6", "show me the picture", "diagram"),
]
# (id, utterance, SOP-210 section the worker is on, expected fact in the answer)
ASK = [
    ("q1", "what temperature should the fridge be at", "3.2", "41"),
    ("q2", "what do I do if it's too warm", "3.2", "shift lead"),
    ("q3", "how long does it need to warm up", "3.3", "30 minutes"),
    ("q4", "what concentration should the sanitizer be", "3.7", "200"),
    ("q5", "how often do I replace it", "3.7", "4 hours"),
    ("q6", "where does the scoop go", "3.6", "holder"),
]
ALL = OPEN + NAV + [(i, u, s) for i, u, s, _ in ASK]


def pcm(i: int) -> str:
    with wave.open(str(HERE / "wav" / f"{i}.wav")) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)
        return base64.b64encode(w.readframes(w.getnframes())).decode()


def ask(client, i, ctx=None, revision=None):
    time.sleep(float(sys.argv[2]) if len(sys.argv) > 2 else 0)  # pace under the Gemini key's RPM quota
    body = {"session_id": str(uuid.uuid4()), "revision": revision, "context": ctx or {},
            "audio": {"format": "pcm_s16le", "sample_rate": 16000, "channels": 1, "data_b64": pcm(i)}}
    t = time.perf_counter()
    r = client.post(f"{RELAY}/v1/ask", json=body).json()
    r["_wall_ms"] = round((time.perf_counter() - t) * 1000)
    return r


def summary(r):
    w = r.get("walkthrough") or {}
    steps = w.get("steps") or []
    return {k: v for k, v in {
        "transcript": r.get("transcript"), "intent": r.get("intent"), "outcome": r.get("outcome"),
        "command": r.get("command"), "glance": r.get("glance"), "body": r.get("body"),
        "source": r.get("source"), "graphic_id": r.get("graphic_id"),
        "needs_clarification": r.get("needs_clarification"), "error": r.get("error"),
        "doc_id": w.get("doc_id"), "steps": len(steps) or None,
        "steps_with_graphic": sum(bool(s.get("graphic_id")) for s in steps) if steps else None,
        "first_step": steps[w["index"]]["label"] + " " + steps[w["index"]]["glance"] if steps else None,
        "latency_ms": r.get("latency_ms"), "wall_ms": r["_wall_ms"],
    }.items() if v is not None}


def main():
    if sys.argv[1] == "prepare":
        (HERE / "utterances.txt").write_text("\n".join(u for _, u, _ in ALL) + "\n", encoding="utf-8")
        return
    out, index = {}, {sid: n for n, (sid, _, _) in enumerate(ALL)}
    with httpx.Client(timeout=90) as c:
        for sid, utter, want in OPEN:
            r = ask(c, index[sid])
            s = summary(r)
            s["expected"], s["said"] = want, utter
            s["pass"] = (s.get("outcome") == "not_found") if want == "not_found" else s.get("doc_id") == want
            out[sid] = s
            if sid == "o3":
                w210 = r["walkthrough"]
            print(sid, "PASS" if s["pass"] else "FAIL", json.dumps({k: s.get(k) for k in ("transcript", "intent", "outcome", "doc_id", "steps", "steps_with_graphic", "first_step", "wall_ms")}))
        steps = {st["label"]: st for st in w210["steps"]}
        here = steps["3.2"]
        for sid, utter, want in NAV:
            s = summary(ask(c, index[sid], {"doc_id": "SOP-210", "step_id": here["step_id"]}, w210["revision"]))
            s["expected"], s["said"], s["pass"] = want, utter, s.get("command") == want
            out[sid] = s
            print(sid, "PASS" if s["pass"] else "FAIL", json.dumps({k: s.get(k) for k in ("transcript", "intent", "outcome", "command", "wall_ms")}))
        for sid, utter, sec, fact in ASK:
            st = steps[sec]
            s = summary(ask(c, index[sid], {"doc_id": "SOP-210", "step_id": st["step_id"]}, w210["revision"]))
            s["expected"], s["said"], s["on_step"] = fact, utter, sec + " " + st["glance"]
            s["pass"] = s.get("outcome") == "answered" and fact.lower() in (s.get("glance", "") + " " + s.get("body", "")).lower()
            out[sid] = s
            print(sid, "PASS" if s["pass"] else "FAIL", json.dumps({k: s.get(k) for k in ("transcript", "outcome", "glance", "source", "graphic_id", "needs_clarification", "wall_ms")}))
    (HERE / "results.json").write_text(json.dumps(out, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
