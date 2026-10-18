# Specs v3 — Build Plan: the worker loop, end to end

**Goal:** a worker opens a procedure by voice in their own words, follows it step by step,
asks a clarifying question whenever they are confused, gets a verified answer (with the
reference picture when there is one) and lands back on the same step. Hands-free on real G2
glasses, with the double nod opening the mic.

Four parts, four people, four branches. Each branch carries its own
`README-V3-PART-N-*.md`: files owned, the work with evidence, build order, acceptance.
Read this file first, then your part.

| Part | Branch | Owner | Owns | Hardest problem |
|---|---|---|---|---|
| 1 | `v3-part-1-lens-ux` | _____ | Lens state machine and screens, phone companion, `types.ts`, app mocks | A clarifying exchange that never loses the worker's place |
| 2 | `v3-part-2-relay-answers` | _____ | `/v1/ask` orchestration, retrieval, generation, verification, illustrations, `schemas.py`, relay mock, eval | Answering every answerable question without ever answering an unverifiable one |
| 3 | `v3-part-3-platform-deploy` | _____ | Deploy, VM config, Gemini quota, app build/pack, health, latency, the diagnostic harness as `make` targets, integration and `TODO.md` | Getting today's code onto the VM and the glasses, and keeping it there |
| 4 | `v3-part-4-field-hardware` | _____ | Real-glasses validation, IMU fixtures and detector tuning, audio/STT on the glasses mic, field reports | Proving it works on a head in a noisy cafe, not just in a test |

Base: tag `v3-base` (on `demo-deploy-fixes`, after `7091112`): relay 740 passed, app 560 passed,
typecheck clean. Integration target is `main` via PRs.

---

## 1. Where the loop stands (live diagnostic, 2026-10-18)

Measured on the current code against the live Tiger DB and Gemini, with synthesized speech and
the app's real Detector / LensController / renderer / API client (`tools/diagnostic/`).

| Loop stage | Status | Evidence |
|---|---|---|
| Double nod opens the mic | **works (synthetic IMU)** | 8/8 asks opened by the real Detector on gravity-vector input; 0 false triggers in 30 s bench work. Real glasses: double nods confirmed in `61b9c1e`, no recorded fixtures yet |
| Open an SOP in your own words | **mostly** | 7/10 prompts open the right SOP at the asked section ("bring up the closing checklist" -> SOP-202 7.1). **Wrong document (2):** "pull a good espresso shot" / "pull up the espresso standards" open SOP-230 (recipes), not SOP-220. "I need to do the cash count for closing" answers one fact instead of opening 7.x |
| Walkthrough scope | **gap** | "making a cappuccino" starts at 3.2 but runs 20 more steps through flat white, americano... before TASK_DONE |
| Step by step by voice | **works** | next / "okay I'm done with that one" / go back / what's next / say that again / show me the picture: 6/6 from real speech |
| Clarifying question on a step | **works for one question** | 18/18 correct after `b4a86d7` + `45c50e5` (was 10/18) |
| Chained follow-up | **gap** | "how hot should the milk be?" OK, "and for a kids drink?" OK, "what about extra hot?" -> not found (verifier rejected twice: `unsupported_number`, `quote_not_found`) |
| Ambiguous question | **gap** | relay returns `needs_clarification: true`; lens and phone both show "Not in approved SOPs". The worker is never asked "which one?" |
| Pictures | **partial** | reference images render on all 6 illustrated SOP-210 steps and with answers. "show me the picture" says "No diagram for this step" when the step has a reference image but no relay diagram; "what does the steam wand look like?" -> not found |
| Answer accuracy | **86 %** | `make eval` 2026-10-17: 31/36 answerable correct (3 not_found, 1 HTTP 504, 1 wrong section); predates today's fixes, not re-run (free-tier quota) |
| Trust | **open** | walkthrough citations quote `step.body` (the authored paraphrase) and are marked verified (`routes/ask.py`, walkthrough branch; TODO §2 "fix first") |
| Off-topic refusal | **works locally, not on the VM** | gate `NOT_FOUND_MIN_SIM=0.68` refuses "walk me through changing a flat tire"; the VM still runs `61b9c1e` with the gate unset |
| Quota | **blocker for a demo** | free-tier key, 15 req/min on `gemini-3.5-flash-lite`; ~15 quick asks exhausted it. STT now retries once (`ed2d983`); embeddings do not retry at all |
| Deployed build | **stale** | VM runs `61b9c1e`; none of the 2026-10-18 loop fixes (`b4a86d7`..`0f3f143`, `ed2d983`, `2c2bb93`) are deployed; app pack points at `sslip.io` |
| Real glasses | **untested for v3** | the v2 task flow, the clarify exchange, field STT accuracy and picture legibility have not run on glasses |

---

## 2. The v3 contract (additive; do this first)

Two optional fields. Old clients ignore them; old relays never send them. Part 2 owns
`relay/src/specs_relay/schemas.py`, Part 1 owns `app/src/types.ts`; both land the same shapes in
hour one, each behind its own mock, and push tag `v3-contract-relay` / `v3-contract-app`.

### Clarify: ask the worker which one they meant

```ts
// app/src/types.ts                         # relay: class Clarify(BaseModel) in schemas.py
export interface Clarify {
  prompt: string;      // <= 40 chars, lens-safe ASCII, e.g. "Which drink?"
  options: string[];   // 2-3 items, each <= 24 chars, e.g. ["Latte", "Cappuccino", "Iced latte"]
}
export interface AskResponse { /* ...v2 fields... */ clarify?: Clarify | null; }
```

- Sent only with `outcome: "not_found"` and `needs_clarification: true`. `verified` stays false.
- Every option is grounded: it is a section heading or document title of a retrieved chunk
  (Part 2 checks this deterministically, like a quote). No invented options.
- The worker answers with a normal ask ("the cappuccino"). The **relay** resolves it: if the
  session's previous response was a clarify, the reply is combined with that question before
  retrieval (`p.sessions`, keyed by `session_id`, which the lens already sends on every ask).
  The lens adds nothing to the request.

### Scoped walkthroughs: finish what was asked for

```ts
export interface Walkthrough { /* ...v2 fields... */ scope?: { start: number; end: number } | null; }
```

- `0 <= start <= index < end <= total`. The lens counts and finishes inside the scope:
  header `k/n` within it, `next` on `end - 1` -> TASK_DONE, `back` stops at `start`.
- A spoken walkthrough sets the scope to its section group ("making a cappuccino" -> 3.2-3.4).
  Assignments (`/v1/assignments/next`) never set it: the supervisor assigned the whole document.
- `steps` stays the whole document, so questions and citations keep their context.

### Unchanged

Every v2 shape and route. `graphic_id`, `needs_clarification`, the command fast path and
`context.step_id` behave as today.

---

## 3. Milestones

| M | Done when | Owners |
|---|---|---|
| **M6** (day 1) | Both contract tags pushed; Part 1 renders `clarify` and `scope` from mocks; Part 2's mock relay returns them; VM redeployed with `v3-base` and the gate set (Part 3) | 1, 2, 3 |
| **M7** | Local live relay: the clarify exchange, scoped walkthroughs, chained follow-ups and picture questions pass `tools/diagnostic/gap_probe.py`; `make eval` (paced) >= 95 % answerable, 0 unverified | 2 |
| **M8** | Simulator against the M7 relay: open -> step -> ambiguous question -> "which drink?" -> answer -> back on the step -> "show me the picture" -> scoped TASK_DONE, by voice, no tap | 1, 2 |
| **M9** | Deployed: the VM runs M8's code, the paid (or quota-safe) key is live, the packed `.ehpk` points at `https://getyourassto.work`, and `make diag-voice` passes against the VM | 3 |
| **M10** | Real glasses, two wearers, cafe noise: the field script in Part 4 passes (5 SOPs opened by voice, 15 clarifying questions, pictures legible, double nod >= 95 %, <= 1 false trigger / 30 min) | 4, with 1 and 2 on call |

## 4. Merge protocol

1. Never commit to `main`. Open a PR from your branch when your milestone is green.
2. Commit and push to your own branch constantly. Small commits.
3. The two contract tags are the only cross-branch dependency in the first hours:
   `git fetch --tags && git merge v3-contract-relay` (or `v3-contract-app`).
4. Stay inside **Files you own**. Need a change elsewhere: one line in the team channel to the
   owner, or a handoff entry in `Context/Projects/Margin.md` (append-only, `Context/README.md`).
5. Integration order into `main`: **3, 2, 1, 4** (deploy plumbing first, then the relay the app
   depends on, then the app, then field fixes).
6. `make test` green before every PR (relay, app + typecheck, portal).
7. Do **not** add `Co-Authored-By: Claude` (or any AI attribution) to commits.

## 5. House rules (every v2 rule still applies)

- Nothing reaches the lens unless it is quoted, verified and human-approved. A clarify option
  is a heading the SOP already has, never generated prose.
- Never truncate a warning, value or acceptance limit to fit the lens. Fail verification instead.
- Never persist raw audio. IMU samples never leave the phone, except committed test fixtures
  (motion only, no audio, no names).
- No secrets in the app bundle or in vault notes. Provider keys live in the relay's `.env` only.
- Synthetic material only (`corpus/`, `corpus/materials/`).
- The Gemini key is shared and rate-limited. Run live checks deliberately and paced
  (`tools/diagnostic/`), never in a tight loop, and say in the channel when you start a long run.
- Do not touch firmware or modify the loaned glasses.
