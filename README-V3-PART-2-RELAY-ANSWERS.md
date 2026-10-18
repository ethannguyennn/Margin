# Part 2 v3 — Relay answers: every answerable question, nothing unverifiable

**Branch:** `v3-part-2-relay-answers` (from tag `v3-base`)
**Owner:** _____
**Read first:** `BUILD-PLAN-V3.md` (§1 where the loop stands, §2 the v3 contract).
**Owns:** what `/v1/ask` decides and says: intent, retrieval, generation, verification,
illustrations, walkthrough assembly, the relay schemas and mock, and the answer-quality eval.
**Milestones:** M6 (`v3-contract-relay` tag + mock), M7 (live relay passes the gap probe and
`make eval` >= 95 %).

---

## 0. Setup

```bash
git fetch && git switch v3-part-2-relay-answers
python -m venv .venv && .venv/Scripts/pip install -e relay[dev]      # once, or reuse yours
.venv/Scripts/python.exe -m pytest relay/tests -q                     # 740 passed, 12 skipped
```

- **Worktree gotcha:** the venv's editable install points at the checkout it was installed
  from. In a worktree run tests with `PYTHONPATH=relay/src` or you test someone else's code.
- **Live relay on Windows:** `tools/diagnostic/run_relay.py` (port 8090, real Tiger DB + Gemini
  from `.env`). uvicorn's CLI picks the Proactor loop and psycopg then cannot connect.
- **Quota:** the Gemini key is free tier, 15 req/min, shared by the team. Unit tests never call
  Gemini. Live runs are paced (`tools/diagnostic/*`, 6-8 s per ask) and announced in the channel.

## 1. Files you own

```
relay/src/specs_relay/routes/ask.py, routes/common.py, routes/procedures.py
relay/src/specs_relay/pipeline/{generate,retrieve,verify,intent,sanitize,mock}.py
relay/src/specs_relay/schemas.py, illustrations.py, walkthrough.py, db.py (read paths)
corpus/illustrations.json, corpus/illustration-prompts.json
eval/run_eval.py, eval/qa.jsonl, eval/README.md, eval/results/
relay/tests/test_{ask_trust,ask_budget,routes,generate,retrieve,verify,intent,illustrations,
                  walkthrough,eval_harness,demo_bank,sanitize}.py
tools/diagnostic/{gap_probe,clarify_rate,voice_loop,gate_scores}.py   # extend with your cases
```

## 2. Files you must NOT touch

`relay/src/specs_relay/main.py`, `config.py`, `obs.py`, `latency.py`, `routes/health.py`,
`deploy/**`, `Makefile`, `.env.example` (Part 3); `pipeline/transcribe.py` (Part 4);
anything under `app/` (Parts 1, 3, 4). Need a setting? Ask Part 3 for the `config.py` field.

## 3. Contract first (hour one)

Add to `schemas.py`, exactly as BUILD-PLAN-V3 §2:

- `class Clarify(BaseModel)`: `prompt` (<= 40), `options` (2-3, each <= 24); a validator on
  `AskResponse` allows `clarify` only with `outcome == "not_found"` and `needs_clarification`.
- `Walkthrough.scope: Scope | None` with `0 <= start <= index < end <= total`.
- Mock (`pipeline/mock.py`): the same three canned cases Part 1 mocks ("how many pumps of
  syrup" -> clarify; "latte" next -> answer; cappuccino walkthrough with a scope).

Push tag `v3-contract-relay`.

## 4. The work (evidence from the 2026-10-18 diagnostic)

### 4.1 Clarify: ask "which one?" and resolve the reply

**Evidence:** "How many pumps of syrup?" and "How hot?" come back `not_found` +
`needs_clarification: true` with nothing the worker can act on.

**Build:**
- When `_answer()` returns `CLARIFY`, build `clarify` from the retrieved chunks: distinct
  section headings (or document titles when the chunks span documents), ranked, 2-3, capped
  and sanitized. Deterministic check: each option equals a retrieved heading/title. If fewer
  than 2 qualify, send no `clarify` (lens shows NOT_FOUND, as today).
- Remember clarify responses in the session (today `p.remember` stores only `answered`
  results; see the `ask()` route). On the next ask in that session, if the previous response
  carried `clarify` and the new transcript is short or matches an option, retrieve and answer
  `previous question + " " + reply` ("How many pumps of syrup? cappuccino").
- Tests: options grounded, caps, < 2 options -> no clarify, reply resolution, a non-matching
  long reply is treated as a new question, the session is per `session_id`.

### 4.2 Chained follow-ups

**Evidence:** on the cappuccino milk step: "How hot should the milk be?" -> answered;
"And for a kids drink?" -> answered; "What about extra hot?" -> not_found.

**Build:** when the session's last response was `answered`, add its cited chunks as candidates
(after the current step's chunk from `_current_step`, deduped, still <= 6) and the previous
question to the generator note, the same way `45c50e5` adds the step. Questions that are
self-contained must still retrieve normally. Tests with a recording generator, like
`test_follow_up_resolves_against_the_current_step`.

### 4.3 Verifier false negatives (correct answers lost)

**Evidence:** "What about extra hot?" failed `unsupported_number` then `quote_not_found`
although SOP-220 4.2 says `"Extra hot" is 160°F (71°C)`. Earlier live runs lost answers to
`glance_too_long` (the 40-char answer glance) and `unsupported_number`. `make eval` 2026-10-17
had 3 answerable questions come back not_found.

**Build:** collect every failing case into `relay/tests/fixtures/verify-false-negatives.jsonl`
(question, chunk text, draft) from eval and live logs (`verify failed (attempt N): <reason>`).
Fix the causes in `verify.py` / `sanitize.py` (typographic quotes, degree and unit glyphs
around numbers, inner quotation marks) and the prompt in `generate.py` (count characters for
the 40-char glance; copy the number with its unit exactly). Never loosen what a number must
match. Every fixture becomes a passing test; every existing hallucination test still fails
closed.

### 4.4 Walkthrough document choice

**Evidence:** "Show me how to pull a good espresso shot" and "Pull up the espresso standards"
open SOP-230 Drink Recipes (the top chunk is "Cappuccino: pull espresso") instead of SOP-220
Espresso Bar - Shot and Milk Standards, which has the shot steps 3.1-3.7.

**Build:** choose the document from the whole retrieved list, not `retrieved.chunks[0]`: score
each candidate document by its chunks' fused rank plus a title/heading match on the transcript
(the document title "Shot and Milk Standards" vs "Drink Recipes"). Keep `_start_index` for the
section. Table test: espresso shot -> SOP-220 3.x; espresso standards -> SOP-220; cappuccino ->
SOP-230 3.x; closing the till -> SOP-202 7.x; kitchen opening -> SOP-210 3.x.

### 4.5 Scoped walkthroughs

Set `walkthrough.scope` for spoken walkthroughs: `start = _start_index(...)`, `end` = one past
the last step of the same section group. Assignments (`routes/assignments.py`) never set it.
Test: cappuccino -> scope 3.2-3.4.

### 4.6 Picture questions

**Evidence:** "What does the steam wand look like?" -> not_found; the `milk-steaming` reference
exists for the cited chunk.

**Build:** a picture-request intent ("what does X look like", "show me the X", "picture of X") in
`intent.py`; answer it with the best-ranked graphic whose reference chunk was retrieved: glance =
the catalog title, citation = the reference quote, `graphic_id` set, verified through
`verify_graphic`. No graphic -> not_found. Keep "show me the picture" (whole utterance) a command.

### 4.7 Trust: walkthrough citations (TODO §2, fix first)

**Evidence:** the walkthrough branch of `_run` builds citations with `quote=s.body` (the authored,
possibly paraphrased body) and marks the response verified.

**Build:** expose each step's stored chunk `text` (the verbatim joined source quotes) from
`db.steps_for` / `walkthrough.build_walkthrough` (an extra field the lens ignores) and cite it.
`_current_step` should use the same verbatim text as its chunk. Test: a paraphrased body never
appears as a citation quote.

### 4.8 Embedding retries

Embeddings have no retry: a 429 from `gemini-embedding-2` fails the ask as `db_down`. Retry once
on `TRANSIENT_CODES` with the 0.4 s backoff inside the timeout, exactly like `ed2d983` does for
STT (`GeminiEmbedder._embed`). Tests with a fake client.

### 4.9 Eval that measures the loop

- Add a `--pace` flag (seconds between asks) to `eval/run_eval.py`; the free tier needs ~6 s.
- Extend `eval/qa.jsonl` with: 5 walkthrough opens (expect doc + start section + scope end),
  5 clarify pairs (question -> expected options -> reply -> expected answer), 5 chained
  follow-ups with step context, 3 picture questions. Score them in `run_eval.py`.
- Record each live run in `eval/results/` with the model and date.

## 5. Build order

1. Contract + mock + tag. 2. 4.7 trust fix. 3. 4.3 false negatives (largest accuracy win).
4. 4.1 clarify, 4.2 follow-ups. 5. 4.4 doc choice, 4.5 scope, 4.6 pictures. 6. 4.8, 4.9.
Run `tools/diagnostic/gap_probe.py` after each step against your local live relay.

## 6. Acceptance (M7)

- `pytest relay/tests` green, a new test per bullet in §4, every hallucination test still fails.
- `eval/run_eval.py --pace 6` on the live relay: >= 95 % answerable correct (>= 35/36),
  0 unverified answers, 4/4 off-domain and 3/3 near-miss refused, both ambiguous cases return a
  grounded `clarify`, and the new loop cases pass.
- `tools/diagnostic/gap_probe.py`: espresso prompts open SOP-220; cappuccino is scoped to 3
  steps; "How many pumps of syrup?" returns options and "cappuccino" resolves it; "what about
  extra hot?" is answered; "what does the steam wand look like?" returns `milk-steaming`.
- `tools/diagnostic/clarify_rate.py`: 18/18 still answered correctly.

## 7. House rules

Every rule in BUILD-PLAN-V3 §5. A clarify option, a picture glance and a walkthrough citation
are all quoted from approved text; when unsure, return not_found. No `Co-Authored-By: Claude`.
