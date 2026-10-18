# Part 1 v3 — Lens & phone UX for the worker loop

**Branch:** `v3-part-1-lens-ux` (from tag `v3-base`)
**Owner:** _____
**Read first:** `BUILD-PLAN-V3.md` (§1 where the loop stands, §2 the v3 contract).
**Owns:** everything the worker sees and touches on the G2 and the phone companion: the lens
state machine, screens, layouts, the phone UI, `types.ts`, and the app-side mocks.
**Milestones:** M6 (`v3-contract-app` tag + mocks), M8 (simulator loop by voice).
**Status (2026-10-18):** §3 and §4.1-4.4 done; M8 passes in the native simulator on the mocks
(`app/tests/evidence/v3/`). Open: §4.5 (waits on Part 4's field reports) and the live M8, which
needs Part 2's relay and Part 3's `client.ts` passing `clarify` through. Details in `app/HANDOFF.md`.

---

## 0. Setup

```bash
git fetch && git switch v3-part-1-lens-ux
cd app && npm ci && npm test && npx tsc --noEmit     # 560 passed, typecheck clean on v3-base
VITE_MOCK=1 npm run dev                              # dev panel: utterance box + Nod / Shake buttons
```

The Even Hub plugin skills still apply (`glasses-ui`, `handle-input`, `test-with-simulator`,
`sdk-reference`); **do not invent SDK APIs**. Simulator smoke: `npm run test:simulator`.
Worktree tip: if you use `git worktree`, link `app/node_modules` from your main checkout.

## 1. Files you own

```
app/src/types.ts               # v3 contract, verbatim from BUILD-PLAN-V3 §2
app/src/state.ts               # CLARIFY screen, scoped walkthroughs, picture command
app/src/ui/screens.ts, layout.ts, sop-graphics.ts, paginate.ts, glyphs.ts, input.ts, fixtures.ts
app/src/main.ts, app/src/lens-link.ts
app/src/mock/index.ts, app/src/mock/tiles.ts      # mock clarify + scope responses
app/src/phone/**                                   # companion UI
app/tests/state.test.ts, controller.test.ts, display.test.ts, phone-*.test.ts(x),
          sop-graphics.test.tsx, session-store.test.ts, glyphs/paginate tests
app/tests/simulator-smoke.mjs, app/tests/evidence/**
tools/diagnostic/loop.test.ts                      # the live app-loop check; extend it with your steps
app/HANDOFF.md
```

## 2. Files you must NOT touch

`app/src/api/client.ts`, `app/src/settings.ts`, `app/app.json`, `app/package.json` (Part 3);
`app/src/motion/**`, `app/src/audio/**` (Part 4); anything under `relay/` (Parts 2 and 3).
Need a field validated in `client.ts`? Ask Part 3 (one line: field name + type).

## 3. Contract first (hour one)

Add `Clarify`, `AskResponse.clarify`, `Walkthrough.scope` to `types.ts` exactly as in
BUILD-PLAN-V3 §2. Extend `validWalkthrough` (`state.ts`) to accept a scope only when
`0 <= start <= index < end <= total`. Add mock responses to `app/src/mock/index.ts`:

- utterance `"how many pumps of syrup"` -> `not_found`, `needs_clarification: true`,
  `clarify: {prompt: "Which size?", options: ["Small", "Medium", "Large"]}` (SOP-230 1.3: pumps
  depend on the size)
- a reply naming a size right after it -> answered ("3 pumps in Medium", SOP-230 1.3)
- `"walk me through making a cappuccino"` -> SOP-230 steps 2.2-4.4, index 4, `scope: {start: 4, end: 7}`
  (3.2-3.4)

Push tag `v3-contract-app`. Part 3 then validates the two fields in `client.ts`.

## 4. The work

### 4.1 Clarify screen (the biggest gap)

**Evidence:** relay sends `needs_clarification: true` for "How many pumps of syrup?" and
"How hot?"; `receive()` in `state.ts` maps every `not_found` to `NOT_FOUND` ("Not in approved
SOPs"). The phone shows the same. The worker is never asked which one they meant.

**Build:**
- New screen `CLARIFY` (add to `SCREENS`). `receive()`: `not_found` + `needs_clarification`
  + a valid `clarify` (2-3 options, caps from §2) -> `CLARIFY`; anything else stays `NOT_FOUND`.
- Render: header `prompt`, main = options one per line, footer hint `nod twice: answer`.
- A double nod / long press opens the mic with `returnTo` = the screen the original question
  was asked from (usually `STEP`), so the eventual answer still returns to the same step.
  Double press / shake = cancel back to that screen. `timeoutFor('CLARIFY')` = the glance timeout.
- The reply is an ordinary ask; the relay resolves it (§2). No new request field.
- Phone: `AnswerDetail` shows the prompt and the options as tappable chips; a tap sends the
  option text through the existing typed-ask path (`lensLink` -> `controller.askText`).
- Tests: CLARIFY entry, malformed clarify falls back to NOT_FOUND, reply -> answer -> back on the
  original step at the same index, cancel, timeout, phone chip sends the option.

### 4.2 Scoped walkthroughs

**Evidence:** "Walk me through making a cappuccino" opens at 3.2 and then runs through flat
white, americano, iced latte (20 more steps) before TASK_DONE.

**Build:** honour `walkthrough.scope` everywhere `index`/`total` are used in `state.ts` and
`screens.ts`: header `k/n` inside the scope, `next` on `end - 1` -> TASK_DONE (progress events
unchanged), `back` floors at `start`, `bar()` uses the scope. No scope = today's behaviour.
Persisted sessions keep the scope (`serializeSession` / `restoreSession`). Phone walkthrough view
shows only the scoped steps, with "show whole procedure" to expand.

### 4.3 "Show me the picture" when the step has a reference image

**Evidence:** `command(s, 'diagram')` (`state.ts`) returns `notice: 'No diagram for this step'`
when `current.diagram` is null, even when `stepGraphic(current)` has a reference image. On STEP
the image is also hidden whenever glance + warning + checkpoint exceed 130 chars
(`stepScreen`), so the worker may never see it.

**Build:** `diagram` with no relay diagram but a `stepGraphic` -> `STEP_DETAILS` page 0 (which
already renders the graphic beside the text). Only "no diagram and no graphic" shows the notice.
Footer on STEP shows `[picture]` when a graphic exists but is hidden. Tests for all three cases.

### 4.4 Answer screens for chained follow-ups

Part 2 makes "and for a kids drink?" / "what about extra hot?" answerable from the session. On
the lens, an answer reached from `ANSWER_GLANCE` (asking again while reading an answer) must
still return to the original `STEP`, not to the previous answer. Add a test chain: STEP ->
answer -> ask -> answer -> dismiss -> STEP at the same index.

### 4.5 Fixes found on hardware (Part 4 reports)

Part 4 files lens legibility issues (font size, image contrast, line breaks, warning visibility)
with photos. You own the fix in `layout.ts` / `screens.ts` / `sop-graphics.ts`. Budget a day.

## 5. Build order

1. Contract + mocks + tag (hour one).
2. 4.1 CLARIFY (state, screen, phone) with tests.
3. 4.2 scope, 4.3 picture command, 4.4 chain test.
4. Simulator run of the M8 script on the mock relay, then on Part 2's local relay
   (`tools/diagnostic/run_relay.py`), evidence PNGs into `app/tests/evidence/v3/`.
5. Hardware fixes as Part 4 reports them.

## 6. Acceptance

- `npm test` + `npx tsc --noEmit` green; new tests for every bullet in §4.
- **M8 in the simulator, no tap anywhere:** double nod -> "walk me through making a cappuccino"
  -> step 1/3 -> "next" -> "how many pumps of syrup?" -> CLARIFY "Which size?" -> double nod ->
  "medium" -> answer -> dismiss -> back on step 2/3 -> "show me the picture" -> picture ->
  "next" x2 -> TASK_DONE at 3/3.
- `tools/diagnostic/loop.test.ts` passes against Part 2's relay, extended with the clarify and
  scope steps above.
- The phone shows the same clarify prompt and options, and tapping one gets the answer.

## 7. House rules

Every rule in BUILD-PLAN-V3 §5. In particular: the lens never shows text the relay did not
verify; a clarify option is shown only as the relay sent it (sanitized, capped), never rewritten.
No `Co-Authored-By: Claude` in commits.
