# Part 1 handoff

## v3 (README-V3-PART-1-LENS-UX.md)

- **Contract:** `types.ts` adds `Clarify`, `AskResponse.clarify` and `Walkthrough.scope` exactly as
  BUILD-PLAN-V3 §2 (tag `v3-contract-app`). `validWalkthrough` accepts a scope only when
  `0 <= start <= index < end <= total`; `validClarify` sanitizes and caps it (prompt <= 40, 2-3
  options <= 24) or the lens shows NOT_FOUND.
- **CLARIFY screen:** header = prompt, one option per line, `nod twice: answer`. Nod / long press /
  press opens the mic; shake / double press / the 20 s glance timeout go back to the step; silence
  keeps the question open. The reply is an ordinary ask (the relay resolves it).
- **Answers return to the step:** an answer asked from CLARIFY or from another answer returns past
  them to the screen the worker was working on (`settled()` in `state.ts`). When nothing sits
  behind them, v2's exact-origin rule is unchanged.
- **Scope:** header `k/n`, the bar, `back`'s floor, `next`'s TASK_DONE and the DONE count all use
  `scopeOf(w)`; no scope = whole procedure. The phone shows the scoped steps with "Show whole
  procedure".
- **Picture command:** `diagram` with no relay diagram but a reference picture opens STEP_DETAILS
  (text beside the picture); STEP shows `[picture]` when the picture had no room.
- **Phone:** `AnswerDetail` shows the clarify prompt and options as chips (`onAsk` -> `askNow`, the
  typed-ask path through the lens); the pill reads "Asking to clarify".
- **Mocks:** "how many pumps of syrup" -> clarify Which size?; a reply naming a size -> its pumps
  answer (once); "walk me through making a cappuccino" -> SOP-230 scoped to 3.2-3.4.
- **Needs Part 3:** `api/client.ts` `validate()` copies fields one by one and drops `clarify` (and
  `graphic_id`), so on a live relay the lens sees a plain not_found until it passes them through.
  `scope` survives (the walkthrough object is passed whole).
- **Evidence:** `tests/v3-loop.test.tsx` (17 tests), M8 in the native simulator
  (`tests/evidence/v3/`), `tools/diagnostic/loop.test.ts` v3 block (opt-in `SPECS_DIAG_V3=1`).
- **Dev environment:** `vite.config.ts` ignores `test-artifacts/` (the simulator's WebView profile
  lives there and reloaded the page forever). After pulling, run `npm install` in `app/`: a stale
  `node_modules` without `@fontsource/carlito` leaves the simulator on a blank page with no error.

## Scaffold

- Official ASR template source: even-realities/evenhub-templates,
  commit `8cb01354f5ee914c5fab97d06e6d13b28eeb5815`.
- Frozen contract: `src/types.ts`; Part 2 owns `src/audio`, `src/api`, `src/obs`,
  `src/mock`. Those directories are deliberately absent here.
- `https://specs.example.com` is the user-approved temporary whitelist origin.
  Replace it when Part 3 provides the live origin.
- No direct STT credentials belong in the WebView bundle.
- Tooling is local to `app/`; port 5174 preserves the earlier starter on 5173.

## Published dependency

`scaffold-app` points to `a9b2ea3` on `part-1-lens-ui`. The tag and branch were
pushed before the lens implementation. Fetch only that tag or cherry-pick its
commit for the app contracts and scaffold. No work has been committed to main.

## Part 2 integration

`src/main.ts` discovers these exact paths and signatures from the role spec:

- `src/api/client.ts`: `ask(req, { signal })`
- `src/audio/capture.ts`: `startCapture(onLevel)`, `stopCapture()`, `isCapturing()`
- `src/obs/sentry.ts`: `initObs()`, `startAsk()`

Once all three exist, they take over in live and VITE_MOCK=1 modes. Before
they land, mock mode uses only the synthetic UI fixture adapter in main;
live mode fails closed to ERROR. No Part 2 directories were created or edited.
Ask/capture failures and cancellations are isolated; late relay responses
cannot replace a newer screen. Audio start/stop share the UI/storage bridge
queue, which is released before waiting for the relay.

Mic source is persisted as `glasses`/`phone`. The frozen capture interface has
no setter for it; Part 2 owns selecting/applying its source. No speculative SDK
call was added. No audio, ordinary answer or transcript is persisted by Part 1.

## Part 4 fixtures

Copy `tests/sanitize-fixtures.json` **verbatim** into the relay suite. This is
the proposed fixture set announced in the current chat. It has not been
agreed or run against Part 4's sanitize.py; no team channel was provided.
The single exported allow-list is `G2_ALLOWED_NON_ASCII` in `ui/glyphs.ts`.

## Acceptance evidence

- Every state/gesture pair has a unit test, including no-ops and root exit.
- Persistence tests simulate a cold start; stale/future/invalid walkthroughs
  are discarded. The 30-minute boundary is strict (`age < 30 minutes`).
- Word-preserving pagination enforces <=450 chars; lens body uses a smaller
  280-char budget for the 184px body box. An impossible oversized token is
  refused rather than split; response routing renders ERROR in that case.
- Three fixed containers, exactly one capture container, brightness 2/4/2,
  no zOrderIndex declarations, no images and **zero rebuildPageContainer calls**.
- Actual official simulator 0.9.5: all fixture outcomes, the complete gesture
  loop, two local walkthrough swipes, multi-page step details and accepted
  native root shutdown. The smoke test records results and screenshots.
- The simulator did not emit SYSTEM_EXIT_EVENT after accepting shutdown;
  mode-1 exit confirmation on physical glasses remains a hardware check.
- The original screenshots use alpha for glyph brightness; composited
  black-background QA captures were inspected for text fit and legibility.
- Hardware font/brightness, live relay/audio and Sentry are untested integrations.
- The placeholder origin must be replaced before live network use. No real
  relay origin or public DSN is present, and no provider keys are bundled.

### Recorded results (2026-10-17)

- `npm test`: **174 tests passed**, six files.
- `npm run test:coverage`: **98.46% lines / 92.07% branches** over the
  modules exercised by the unit suites. `main.ts` is exercised by the simulator
  test, not included in that unit coverage figure.
- `npm run test:simulator`: **29 screen assertions passed**, five fixture
  requests, step navigation made no extra request, native shutdown accepted,
  zero console errors. See `tests/evidence/simulator-results.json`.
- `npm run pack`: succeeded; `specs.ehpk` generated with minimum Even App
  version **2.2.10** resolved from SDK **0.0.16**.
- The synthetic visual captures in `tests/evidence/` were inspected. Native
  shutdown leaves a cleared display, captured by `root-exit-glasses-preview.png`.
