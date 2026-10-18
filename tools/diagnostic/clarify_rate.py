"""Repeat each clarifying question (text, step context set) and count lens-visible outcomes."""
import json
import time
import uuid
from collections import Counter

import httpx

from voice_loop import ASK, RELAY

with httpx.Client(timeout=90) as c:
    w = c.post(f"{RELAY}/v1/ask", json={"session_id": str(uuid.uuid4()),
               "text": "guide me through the kitchen opening checklist"}).json()["walkthrough"]
    steps = {s["label"]: s for s in w["steps"]}
    rows = []
    for rep in range(3):
        for sid, utter, sec, fact in ASK:
            time.sleep(8)  # free-tier key: 15 req/min, up to 2 generate calls per ask
            r = c.post(f"{RELAY}/v1/ask", json={"session_id": str(uuid.uuid4()), "text": utter, "revision": w["revision"],
                       "context": {"doc_id": "SOP-210", "step_id": steps[sec]["step_id"]}}).json()
            # What the lens does with it (state.ts receive): answered needs a non-empty body.
            if r["outcome"] == "answered":
                lens = "ANSWER" if r["body"].strip() else "ERROR(empty body, pre-b4a86d7 lens)"
                right = fact.lower() in (r["glance"] + " " + r["body"]).lower()
                lens += "" if right else " WRONG"
            else:
                lens = r["outcome"].upper() + (" clarify" if r.get("needs_clarification") else "")
            rows.append((sid, lens, r.get("glance"), r.get("source")))
            print(sid, rep, lens, "|", r.get("glance"), "|", r.get("source"), flush=True)
    print(json.dumps({sid: Counter(l for s, l, *_ in rows if s == sid) for sid, *_ in ASK}, indent=1))
