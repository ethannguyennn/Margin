# Part 2 — Audio Capture, Relay Client & App Observability

**Branch:** `part-2-app-io`
**Owns:** everything that crosses the app's boundary — the glasses mic, the
HTTP call to the relay, the mock layer that unblocks the whole team, and
Sentry in the WebView.

**Milestones:** M1 (mock layer), M2 (client against real relay), M3 (real PCM
from the glasses mic). M3 on real hardware is the single riskiest item in the
build — get a transcript on the lens early.

---

## 0. Before writing code

```
/plugin marketplace add even-realities/everything-evenhub
/plugin install everything-evenhub
```

Skills you will live in: `handle-input`, `device-features`,
`test-with-simulator`, `sdk-reference`, `build-and-deploy`.

Docs: https://hub.evenrealities.com/docs/

**Do not invent SDK APIs.** Verify every call against
`@evenrealities/even_hub_sdk` types. If you cannot confirm a signature, leave
`// TODO(verify-sdk): <link>` and keep going. Never stall.

---

## 1. Files you own

```
app/src/audio/capture.ts      # audioControl + PCM ring buffer
app/src/api/client.ts         # fetch to relay: timeout, abort, retry, errors
app/src/obs/sentry.ts         # browser Sentry init, ask transaction + spans
app/src/mock/                 # canned responses for VITE_MOCK=1
app/src/settings.ts           # mic-source toggle, persisted
app/tests/audio.test.ts, app/tests/client.test.ts
app/.env.example              # VITE_RELAY_ORIGIN, VITE_SENTRY_DSN, VITE_MOCK
```

## 2. Files you must NOT touch

`app/src/main.ts`, `app/src/state.ts`, `app/src/types.ts`, `app/src/ui/*`,
`app/app.json`, `app/package.json` (Part 1 — ask in the channel if you need a
dep added), `relay/`, `db/`, `corpus/`, `eval/`, root `Makefile` (Part 3), and
**`main`**.

## 3. Your one dependency

Part 1 pushes the tag `scaffold-app` inside the first hour (Vite/TS skeleton,
`app.json`, `app/src/types.ts`). Then:

```bash
git fetch --tags && git merge scaffold-app
```

Until it lands, **do not wait.** Write your four modules as standalone files
and paste the `AskRequest` / `AskResponse` types from section 6 into a
temporary `app/src/types.ts`; at merge take Part 1's copy:
`git checkout --theirs app/src/types.ts`.

---

## 4. Audio capture (`audio/capture.ts`)

Push-to-talk, not always-on. The mic is open **only** while the user is
asking — this is both the privacy story and the only thing that survives
Android backgrounding.

- API: `audioControl(true|false, source?)`. `source` is `Glasses` (4-mic
  array, the default) or `Phone`.
  **`createStartUpPageContainer` must have already run before `Glasses`
  works** — so capture can only start after Part 1's boot completes.
- PCM arrives in `event.audioEvent.audioPcm`: **16 kHz, signed 16-bit LE,
  mono.** Append chunks to a ring buffer.
- Permissions live in `app.json` (`g2-microphone`, plus `phone-microphone`
  only if we ship the phone fallback) — Part 1 owns that file; send them the
  one-line request.
- Stop on any of: second press, `MAX_AUDIO_SECONDS` cap (**8 s**), or
  double-press cancel. Always call `audioControl(false)`.
- **Re-check mic state on `visibilitychange`.** Android WebView may have been
  suspended; never assume a live stream. On foreground, treat the stream as
  dead and re-enable on the next press.
- Compute a 0..1 RMS level per chunk and feed `onLevel` so Part 1 can draw the
  live input meter.
- Expose a mic-source toggle through `settings.ts` (persisted in
  localStorage, default `Glasses`, fallback `Phone`) — we need the A/B on real
  hardware.
- **Never persist raw audio.** In memory only; base64 it, send it, drop the
  buffer. No IndexedDB, no localStorage, no files, not even for debugging.

Public surface (Part 1 codes against exactly this):

```ts
export function startCapture(onLevel: (rms01: number) => void): Promise<void>;
export function stopCapture(): Promise<{ data_b64: string; sample_rate: 16000 }>;
export function isCapturing(): boolean;
```

## 5. Relay client (`api/client.ts`)

```ts
export function ask(req: AskRequest, opts?: { signal?: AbortSignal }): Promise<AskResponse>;
export function health(): Promise<{ ok: boolean; mock: boolean; db: string; version: string }>;
export function logDeviation(text: string, ctx?: { doc_id?: string; step_id?: string }): Promise<{ deviation_id: string; notified: boolean }>;
```

Rules:

- Base URL from `import.meta.env.VITE_RELAY_ORIGIN`. It must be **the exact
  full origin** in `app.json`'s whitelist (`https://api.example.com` — no
  wildcards, no bare hosts), or the request is blocked by the Even network
  layer before CORS even matters.
- Timeout **50 s** on `/v1/ask` via `AbortController` (two 20 s generation attempts
  plus STT/retrieval); a new press aborts the
  in-flight request.
- One retry on a network error or 5xx. **Never retry a 4xx.** Never retry
  twice — the technician would rather see ERROR than wait.
- Always send `x-session-id`. Let the Sentry SDK attach `sentry-trace` and
  `baggage` so the relay can continue the trace.
- Map everything that is not a valid 200 body onto the contract error shape so
  Part 1 only ever has to switch on `outcome`:
  `{ trace_id, outcome: 'error', error: { code, message } }`.
  Codes: `stt_failed | db_down | llm_timeout | bad_request`, plus `network`
  and `timeout` which you generate client-side.
- Validate the response minimally before handing it up: `outcome` is a known
  value, and when `outcome === 'answered'`, `verified === true` and
  `citations.length > 0` — otherwise downgrade it to `not_found`. The relay
  should never send an unverified answer; this is the belt to its braces.
- `VITE_MOCK=1` short-circuits the whole module to `app/src/mock/`. No network.

## 6. The frozen contract (do not change alone)

Any change needs agreement from Parts 1-5 in the team channel.

### `POST /v1/ask`

Request:

```json
{
  "session_id": "uuid",
  "audio": { "format": "pcm_s16le", "sample_rate": 16000, "channels": 1, "data_b64": "..." },
  "text": null,
  "revision": null,
  "context": { "doc_id": null, "step_id": null }
}
```

Exactly one of `audio` / `text` is present. `text` bypasses STT — use it for
every test and for typed input.

Response 200:

```json
{
  "trace_id": "string",
  "transcript": "how tight is the m5 on the mounting bracket",
  "intent": "question",
  "outcome": "answered",
  "glance": "Step 4.2: torque M5 to 4 N-m",
  "body": "Torque all four M5 bracket screws to 4 N-m ...",
  "source": "SOP-114 Sec 4.2 rev C",
  "citations": [ { "chunk_id": "SOP-114:C:4.2", "doc_id": "SOP-114", "revision": "C", "section": "4.2", "quote": "Torque ... to 4 N-m" } ],
  "verified": true,
  "walkthrough": null,
  "latency_ms": { "stt": 0, "embed": 0, "retrieve": 0, "generate": 0, "verify": 0, "total": 0 }
}
```

- `intent`: `question | walkthrough | deviation | repeat | unknown`
- `outcome`: `answered | not_found | logged | clarify | error`
- `walkthrough` (only when `intent == walkthrough`):
  `{ doc_id, revision, title, total, index, steps: [ { step_id, label, glance, body } ] }`
  — all steps at once, the app navigates locally.
- `not_found`: `glance = "Not in approved SOPs"`,
  `body = "No matching procedure. Try rephrasing or ask your supervisor."`,
  `citations = []`, `verified = false`.
- Error (4xx/5xx): `{ trace_id, outcome: "error", error: { code, message } }`.

### Other routes

```
GET  /v1/health                               -> { ok, mock, db, version }
POST /v1/deviation                            -> { deviation_id, notified }
GET  /v1/procedures                           -> [ { doc_id, title, revision, status } ]
GET  /v1/procedures/{doc_id}/steps?revision=  -> ordered steps
```

### TypeScript types

`app/src/types.ts` is **owned by Part 1** and is exactly the above. Paste this
locally only until `scaffold-app` lands:

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
  glance: string;
  body: string;
  source: string;
  citations: Citation[];
  verified: boolean;
  walkthrough: Walkthrough | null;
  latency_ms: Latency;
  error?: { code: string; message: string };
}
```

## 7. Mock layer (`src/mock/`) — build this FIRST

Your mock module unblocks Part 1 for the entire hackathon, so it is hour one,
not hour ten. Ship at least these canned `AskResponse` fixtures, keyed by a
substring of the transcript:

| trigger | outcome |
|---|---|
| "how tight" / "torque" / "m5" | `answered`, SOP-114 Sec 4.2 rev C, verified |
| "guide me" / "walk me through" | `walkthrough`, 7 steps |
| "clean" / "disinfect" | `answered`, SOP-120, body long enough to paginate to 2 pages |
| "coffee" / anything unmatched | `not_found` |
| "log deviation" | `logged` |
| "boom" | `error` with code `llm_timeout` |

Also mock `startCapture`/`stopCapture` with a fake 1.5 s level ramp and an
artificial 900 ms `ask` delay so THINKING is actually visible in the simulator.
Export a `MOCK_DELAY_MS` you can set to 0 in tests.

## 8. Observability (`obs/sentry.ts`)

- `@sentry/browser` with **tracing and logs** enabled. Replay only if it works
  in the WebView — **do not block on Replay.**
- One transaction per ask, named `ask`, with spans `capture`, `upload`,
  `render`. The relay continues the same trace server-side via the
  `sentry-trace` / `baggage` headers, so do not strip them.
- DSN from `VITE_SENTRY_DSN` (a public DSN — fine in the bundle; **no other
  secrets ever go in the app**, `.ehpk` contents can be extracted).
- Optional, do last: route Sentry through the relay with the SDK's `tunnel`
  option (`<relay>/v1/sentry-tunnel`, Part 3 owns the route) so the app only
  needs one whitelisted origin.
- Latency budget you are instrumenting against (p50): upload 300 ms, STT 600,
  embed+retrieve 300, generate 1200, verify 50, render 300. The pitch number is
  **end-of-speech to glance <= 3 s**.

## 9. Build order

1. `src/mock/` + the fixture table. Push it and tell Part 1. (Hour one.)
2. `api/client.ts` against the mock, then against Part 3's mock relay
   (`MOCK_MODE=1`) once `/v1/health` answers.
3. `obs/sentry.ts` — init + the `ask` transaction.
4. `audio/capture.ts` in the simulator (phone source), then on real glasses.
5. Hardware pass: glasses mic vs phone mic, one person speaking vs a person
   across a table.

## 10. Acceptance

- **M2 done:** with Part 3's relay running, the simulator shows a real response
  from `/v1/ask`; killing the relay mid-request shows Part 1's ERROR screen and
  a second press retries cleanly.
- **M3 done:** on real glasses, speaking a sentence shows the correct
  transcript on the lens within ~2 s.
- [ ] Mic is provably closed outside LISTENING (log `audioControl` calls).
- [ ] 8 s cap enforced; a 20 s press sends 8 s of audio, not 20.
- [ ] Phone locked 5 min then relaunched: next press still captures.
- [ ] Permission denied: clear message, no crash, no infinite retry.
- [ ] Zero raw audio anywhere on disk (grep your diff for any write path).

## 11. Merge protocol (read once, it is short)

1. **Never commit to `main`.** `main` stays empty until the integration merge.
2. Commit and push to your own branch constantly. Small commits.
3. Pull `scaffold-app` from Part 1 when announced (section 3).
4. Stay inside **Files you own**. If you need a change in someone else's file,
   post a one-line request in the channel; do not edit it.
5. Integration order into `main`: 1, 3, 2, 4, 5.
6. Do **not** add `Co-Authored-By: Claude` to commits.

## 12. House rules

- Never persist raw audio. In-memory only.
- No secrets in the app bundle beyond the public Sentry DSN.
- Synthetic SOPs only.
- Do not touch firmware or modify the loaned glasses.
- The simulator does not cover backgrounding, real permissions or BLE timing.
  Those three are yours, and only hardware proves them.
