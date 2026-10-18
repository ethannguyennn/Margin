"""Text probes for loop gaps on the merged relay: natural opens, ambiguity, chained follow-ups,
walkthrough scope. Paced for the free-tier Gemini key."""
import json
import time
import uuid

import httpx

RELAY = "http://127.0.0.1:8090"
SID = str(uuid.uuid4())  # one worker session, so "repeat"/history behave as on the lens


def ask(c, text, ctx=None, rev=None, sid=SID):
    time.sleep(7)
    t = time.perf_counter()
    r = c.post(f"{RELAY}/v1/ask", json={"session_id": sid, "text": text, "revision": rev, "context": ctx or {}}).json()
    w = r.get("walkthrough") or {}
    s = {"q": text, "intent": r.get("intent"), "outcome": r.get("outcome"), "glance": r.get("glance"),
         "body": r.get("body"), "source": r.get("source"), "clarify": r.get("needs_clarification"),
         "graphic": r.get("graphic_id"), "ms": round((time.perf_counter() - t) * 1000)}
    if w:
        st = w["steps"]
        s.update(doc=w["doc_id"], start=st[w["index"]]["label"] + " " + st[w["index"]]["glance"],
                 steps_left=w["total"] - w["index"], labels=[x["label"] for x in st[w["index"]:]][:12])
    print(json.dumps(s), flush=True)
    return r


with httpx.Client(timeout=90) as c:
    # Natural ways to open a procedure (Codex's intents + the new gate).
    for q in ["Pull up the espresso standards.", "Open the cleaning procedure.", "Bring up the closing checklist.",
              "Let's start the back of house opening.", "I need to do the cash count for closing.",
              "Show me how to pull a good espresso shot."]:
        ask(c, q)
    # Walkthrough scope: does "making a cappuccino" stop after the cappuccino?
    cap = ask(c, "Walk me through making a cappuccino.")["walkthrough"]
    # Ambiguity: what does the worker see?
    ask(c, "How many pumps of syrup?")
    ask(c, "How hot?")
    # Chained follow-ups on the cappuccino's milk step.
    milk = next(s for s in cap["steps"] if "milk" in s["glance"].lower() and s["label"].startswith("3."))
    ctx = {"doc_id": cap["doc_id"], "step_id": milk["step_id"]}
    ask(c, "How hot should the milk be?", ctx, cap["revision"])
    ask(c, "And for a kids drink?", ctx, cap["revision"])
    ask(c, "What about extra hot?", ctx, cap["revision"])
    # Picture request as a question rather than the command.
    ask(c, "What does the steam wand look like?", ctx, cap["revision"])
