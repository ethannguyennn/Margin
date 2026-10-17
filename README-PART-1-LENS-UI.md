# Part 1 — Lens UI & State Machine

**Branch:** `part-1-lens-ui`
**Owns:** everything the technician sees on the G2 display, plus the app state
machine. You are the demo. If your part works in the simulator with
`VITE_MOCK=1`, the project has a demo even if nothing else lands.

**Milestones:** M0 (app scaffold) + M1 (hello lens). You also publish the
`scaffold-app` tag that the rest of the app side depends on — do that first.

---

## 0. Before writing code

Install the official plugin and use its skills instead of guessing SDK calls:

```
/plugin marketplace add even-realities/everything-evenhub
/plugin install everything-evenhub
```

Skills you will live in: `quickstart`, `template`, `glasses-ui`,
`handle-input`, `test-with-simulator`, `sdk-reference`, `design-guidelines`.

Docs: https://hub.evenrealities.com/docs/
Templates: https://github.com/even-realities/evenhub-templates — **start from
the `asr` template.**

**Do not invent SDK APIs.** Where this README names a call, verify the exact
signature against `@evenrealities/even_hub_sdk` types. If you cannot confirm
it, leave `// TODO(verify-sdk): <link>` and keep going. Never stall.

---

## 1. Files you own

```
app/                          # whole scaffold: package.json, vite config, tsconfig
app/app.json                  # permissions + network whitelist
app/src/main.ts               # waitForEvenAppBridge(), boot, wiring
app/src/state.ts              # states, transitions, persisted session
app/src/types.ts              # SHARED contract types (section 7)
app/src/ui/layout.ts          # container definitions
app/src/ui/screens.ts         # one render fn per state
app/src/ui/paginate.ts        # 400-500 char pagination
app/src/ui/glyphs.ts          # sanitizeForG2()
app/tests/                    # your unit tests
```

## 2. Files you must NOT touch

`app/src/audio/`, `app/src/api/`, `app/src/obs/`, `app/src/mock/` (Part 2),
`relay/`, `db/`, `corpus/`, `eval/`, root `Makefile`, root `.env.example`
(Part 3), and **`main`**.

---

## 3. Hard platform constraints (not suggestions)

- Display per eye: **576 x 288**, 4-bit greyscale green. No color, no
  background fill.
- Max **8 non-image containers + 4 image containers** per page. Exactly one
  container has `isEventCapture: 1`.
- Text containers: plain text, left/top aligned. No font size, bold, italic.
  Wraps at container width. Firmware scrolls overflow only in the container
  that captures events.
- Full screen holds roughly **400-500 chars**.
  `createStartUpPageContainer` / `rebuildPageContainer`: **1,000 char** cap.
  `textContainerUpgrade`: **2,000 char** cap.
- `textContainerUpgrade` is in-place and flicker-free. **Use it for every text
  change.** Rebuild the page only when the container *set* changes.
- `textColor` = brightness level **0-4**, not a color. Level 0 may be invisible.
- One firmware font face; characters outside it are silently dropped. No emoji.
- Declare `zOrderIndex` on all containers or on none.
- Input events: `CLICK_EVENT(0)`, `DOUBLE_CLICK_EVENT(3)`,
  `SCROLL_TOP_EVENT(1)`, `SCROLL_BOTTOM_EVENT(2)`, `LONG_PRESS_EVENT(9)`,
  `LONG_PRESS_RELEASE_EVENT(10)`. The OS claims some long presses — **do not
  depend on long press.**
- **Root page double-tap must exit the app.** QA gate; failing it fails review.
- Bluetooth bandwidth ~10-30 KB/s. Send text, never frames.
- Locales: ship `en` only.

---

## 4. Layout (`ui/layout.ts`)

Design principle, "Quiet Tech": dark by default, information appears only on
demand, glanceable first, details on tap, never more than ~3 short lines
unless the user expands.

| Container | y range | brightness | role |
|---|---|---|---|
| header | 0-40 | 1-2 (dim) | state / progress |
| main | 48-232, `isEventCapture: 1`, `paddingLength ~8` | 4 | glance or body text |
| footer | 240-288 | 1-2 (dim) | source tag + gesture hint |

## 5. Screens (`ui/screens.ts`)

Real output must be ASCII-safe after `sanitizeForG2()`.

```
IDLE                      LISTENING                THINKING
+--------------------+    +--------------------+   +--------------------+
|                    |    | LISTENING          |   | ...                |
|   (blank / dim)    |    |  _.-^-._           |   | checking SOPs      |
| press to ask       |    | press to send      |   |                    |
+--------------------+    +--------------------+   +--------------------+

ANSWER (glance)                         ANSWER (expanded, page 1/2)
+-------------------------------+       +-------------------------------+
| Step 4.2: torque M5 to 4 N-m  |       | Torque all four M5 bracket    |
|                               |       | screws to 4 N-m in a star     |
| SOP-114 Sec 4.2 rev C     [+] |       | pattern. Use calibrated wrench|
+-------------------------------+       | SOP-131 Sec 3.        1/2  v  |
                                        +-------------------------------+

NOT FOUND                               WALKTHROUGH
+-------------------------------+       +-------------------------------+
| Not in approved SOPs          |       | SOP-114 rev C   step 3/7      |
| Try rephrasing or ask your    |       | [===....]                     |
| supervisor.                   |       | Seat bracket on dowel pins.   |
+-------------------------------+       | swipe: next   press: details  |
                                        +-------------------------------+

ERROR
+-------------------------------+
| Something went wrong          |
| press to retry                |
+-------------------------------+
```

The LISTENING level meter and the walkthrough progress bar use the allow-listed
block glyphs from section 8 (lower blocks for the meter, heavy/light rules for
the bar). The ASCII above is only so this README renders everywhere.

Also render the **first-run privacy screen**, shown exactly once (flag in
localStorage): `"Audio is processed to answer, not stored. Ask before
recording others."`

## 6. State machine (`state.ts`)

```
IDLE -> LISTENING -> THINKING -> ANSWER_GLANCE <-> ANSWER_EXPANDED
THINKING -> NOT_FOUND | ERROR | WALKTHROUGH | LOGGED
WALKTHROUGH -> ANSWER_EXPANDED (details) -> WALKTHROUGH
any state -> IDLE on timeout
```

- Glance auto-dims to IDLE after **20 s**. A walkthrough persists.
- Persist via `setLocalStorage` / `getLocalStorage` (sandboxed per
  `package_id`): `session_id`, current walkthrough (`doc_id`, `revision`,
  `index`), mic source, privacy-screen-seen flag.
- On cold start, restore the walkthrough if it is **< 30 min old**.
- Android WebView may be suspended in the background (treat as cold start);
  iOS keeps running. Re-render and re-arm on `visibilitychange`.

### Gesture map

| Gesture | IDLE | LISTENING | ANSWER_GLANCE | ANSWER_EXPANDED | WALKTHROUGH |
|---|---|---|---|---|---|
| Press (CLICK) | start listening | stop + send | expand | collapse | step details |
| Scroll up/down | - | - | - | prev/next page | prev/next step |
| Double press | **exit app** | cancel -> IDLE | dismiss -> IDLE | collapse | exit -> IDLE |
| Long press | unused | unused | unused | unused | unused |

Exit uses the SDK's exit/shutdown call — `// TODO(verify-sdk)` until confirmed
in `sdk-reference`.

Walkthrough navigation is **local**: the relay returns all steps at once, so
swiping must never hit the network.

## 7. Interfaces you consume (Part 2 implements them)

Code against these signatures from hour one. Part 2's mock module satisfies
them under `VITE_MOCK=1`.

```ts
// app/src/api/client.ts    (Part 2)
export function ask(req: AskRequest, opts?: { signal?: AbortSignal }): Promise<AskResponse>;

// app/src/audio/capture.ts (Part 2)
export function startCapture(onLevel: (rms01: number) => void): Promise<void>;
export function stopCapture(): Promise<{ data_b64: string; sample_rate: 16000 }>;
export function isCapturing(): boolean;

// app/src/obs/sentry.ts    (Part 2)
export function initObs(): void;
export function startAsk(): { finishSpan(name: string): void; end(outcome: string): void };
```

Until Part 2 pushes, stub these yourself in `app/src/mock/local-stubs.ts` and
delete that file at merge.

### The frozen contract (do not change alone)

Any change here needs agreement from Parts 1-5 in the team channel.

`app/src/types.ts` is **yours** and is the single source of truth for the app
side. Commit it in the `scaffold-app` tag:

```ts
export type Intent = 'question' | 'walkthrough' | 'deviation' | 'repeat' | 'unknown';
export type Outcome = 'answered' | 'not_found' | 'logged' | 'clarify' | 'error';

export interface Citation { chunk_id: string; doc_id: string; revision: string; section: string; quote: string; }
export interface Step { step_id: string; label: string; glance: string; body: string; }
export interface Walkthrough { doc_id: string; revision: string; title: string; total: number; index: number; steps: Step[]; }
export interface Latency { stt: number; embed: number; retrieve: number; generate: number; verify: number; total: number; }

export interface AskRequest {
  session_id: string;
  audio?: { format: 'pcm_s16le'; sample_rate: 16000; channels: 1; data_b64: string };
  text?: string | null;
  revision?: string | null;
  context?: { doc_id: string | null; step_id: string | null };
}

export interface AskResponse {
  trace_id: string;
  transcript: string;
  intent: Intent;
  outcome: Outcome;
  glance: string;      // <= 60 chars, ASCII
  body: string;        // <= 450 chars, ASCII
  source: string;      // "SOP-114 Sec 4.2 rev C"
  citations: Citation[];
  verified: boolean;
  walkthrough: Walkthrough | null;
  latency_ms: Latency;
  error?: { code: string; message: string };
}
```

`not_found` arrives as `glance = "Not in approved SOPs"`,
`body = "No matching procedure. Try rephrasing or ask your supervisor."`,
`citations = []`, `verified = false`. Render NOT FOUND on
`outcome === 'not_found'`, ERROR on `'error'`, WALKTHROUGH when
`walkthrough !== null`, LOGGED on `'logged'`.

**Never display text with `verified === false` as an answer.** That is the
whole product thesis. NOT FOUND and ERROR are the only unverified-safe renders.

## 8. Glyph sanitizer (`ui/glyphs.ts`)

Identical rules to the relay's `sanitize.py` (Part 4), same test fixtures.

| In | Out |
|---|---|
| section sign | `Sec ` |
| middot, bullet | `-` |
| degree sign | ` deg` |
| micro sign | `u` |
| ohm sign | ` ohm` |
| en dash, em dash | `-` |
| curly double / single quotes | `"` and `'` |
| multiplication sign | `x` |
| plus-minus sign | `+/-` |
| >= and <= signs | `>=` `<=` |
| right arrow | `->` |
| emoji / any other non-ASCII not allow-listed | dropped |

Allow-listed non-ASCII, kept in **one exported constant** so it can be
narrowed after hardware testing:

```
U+25B2 U+25B3 U+25B6 U+25B7 U+25BC U+25BD U+25C0 U+25C1
U+25CF U+25CB U+25A0 U+25A1 U+2605 U+2606
U+2501 U+2500 U+2588 U+2587 U+2586 U+2585 U+2584 U+2583 U+2582 U+2581
U+256D U+256E U+256F U+2570 U+2502
```

Test on hardware: section sign, middot, degree, micro, ohm. Default to the
ASCII fallback above until confirmed.

## 9. Build order

1. Scaffold from the `asr` template, `npm i`, boot in the simulator
   (`@evenrealities/evenhub-simulator`). Commit.
2. Write `types.ts` and `app.json` (network permission with a **full origin**
   whitelist entry `https://margin.<domain>` — no wildcards, no bare hosts —
   plus `g2-microphone`). Commit, then
   `git tag scaffold-app && git push origin part-1-lens-ui --tags`, and
   **announce it in the channel.** Everything else of yours comes after.
3. `glyphs.ts` + `paginate.ts` with unit tests first — pure functions, and the
   only things here with real edge cases.
4. `layout.ts`, then `screens.ts` driven by hardcoded fixture objects.
5. `state.ts` as a transition table; unit-test every transition.
6. Wire `main.ts`: bridge ready -> privacy screen -> IDLE; gesture handler ->
   state machine -> render.

## 10. Acceptance (M1 done)

- [ ] `VITE_MOCK=1 npm run dev` in the simulator: full
      `IDLE -> LISTENING -> THINKING -> ANSWER_GLANCE -> ANSWER_EXPANDED -> IDLE`
      loop driven only by gestures.
- [ ] NOT FOUND, ERROR, WALKTHROUGH (swipe two steps) and LOGGED all reachable
      from mock fixtures.
- [ ] Double-press on the root page exits.
- [ ] `sanitizeForG2` and `paginate` unit tests pass. Pagination never emits a
      page over 450 chars and never splits mid-word.
- [ ] Every text update goes through `textContainerUpgrade`; the page is
      rebuilt only on container-set changes (grep your own diff for
      `rebuildPageContainer`).
- [ ] State restored correctly after a simulated cold start.

## 11. Merge protocol (read once, it is short)

1. **Never commit to `main`.** `main` stays empty until the integration merge.
2. Commit and push to your own branch constantly. Small commits.
3. Two scaffold tags are the only cross-branch dependency:
   - `scaffold-app` — **you** push it within the first hour.
   - `scaffold-relay` — Part 3 pushes it within the first hour.
4. Stay inside **Files you own**. If you need a change in someone else's file,
   post a one-line request in the channel; do not edit it.
5. Integration order into `main`: 1, 3, 2, 4, 5.
6. Do **not** add `Co-Authored-By: Claude` to commits.

## 12. House rules

- Never persist raw audio anywhere. You only ever hold text.
- No secrets in the app bundle — `.ehpk` contents can be extracted. The only
  app-side env values are `VITE_RELAY_ORIGIN`, `VITE_SENTRY_DSN` (public DSN)
  and `VITE_MOCK`.
- Synthetic SOPs only. Never ingest or display real employer documents.
- Do not touch firmware or modify the loaned glasses in any way.
- Do not copy code from other Even Hub apps.
