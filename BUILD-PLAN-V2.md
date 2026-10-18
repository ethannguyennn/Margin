# Specs v2 — Build Plan

v1 proved the trust layer: ask a question, get an answer quoted from an approved
SOP, or an honest "Not in approved SOPs". v1 does not do what the product is for:

| What we promised | v1 reality | v2 |
|---|---|---|
| Employer hands the worker their instructions | SOPs are hand-written markdown in `corpus/`, seeded by a developer | Supervisor uploads a PDF, DOCX, text or a phone photo of a paper SOP in a web portal; Specs turns it into an interactive procedure; supervisor reviews, approves, assigns |
| Interactive, progressive steps | Walkthrough exists, but only if the worker *says* "walk me through" and the retriever guesses the right doc | The assigned task is waiting on the lens; one step at a time, with warnings and checkpoints; progress is reported back to the supervisor |
| Hands-free | Every interaction needs a tap on the temple; the mic needs a press to open **and** a press to send | Double head-nod opens the mic, silence closes it, voice drives navigation ("next", "back", "show diagram"); head-shake cancels. Taps stay as a fallback |
| Diagrams | None. Text containers only | Per-step diagrams on the lens: figures cropped from the uploaded material, or schematics generated from it, rendered to the G2's 4-bit greyscale |

The trust rule does not change and now applies to *authoring* as well as
answering: **nothing reaches the lens unless it is quoted from the employer's
material, passed the deterministic verifier, and was approved by a human.**

---

## 1. The five parts

Same five people, same lanes as v1, new branches. Each branch has a
`README-PART-N-*.md` with files owned, interfaces, build order and acceptance.

| Part | Branch | Owns | Hardest problem |
|---|---|---|---|
| 1 | `part-1-lens-hands-free-ui` | Lens state machine v2, step / diagram / pairing / calibration screens, mixed text+image layouts, `types.ts` | Hands-free UX that never loses the worker's place |
| 2 | `part-2-motion-voice-io` | IMU nod/shake detection + calibration, voice endpointing, capture v2, client v2 (pairing, assignments, progress, diagrams), mocks | A nod detector that fires on purpose and not when someone looks down at a bench |
| 3 | `part-3-relay-platform` | Contract v2 server side, every new route, device + portal auth, uploads, `command` fast path in `/v1/ask`, deploy | Keeping one orchestrator while the surface triples |
| 4 | `part-4-conversion-diagrams` | Material -> procedure conversion, draft verifier, diagram crop/generate/render, command intents, conversion eval | Converting messy material without inventing a single number |
| 5 | `part-5-portal-data` | Migration 002, `db.py` v2, publish-on-approve, the employer portal, progress board, synthetic demo materials | A portal a supervisor can use in five minutes |

Integration order into `main`: **1, 3, 2, 4, 5** (unchanged). Contract first.

### Base

Every v2 branch starts from the same commit: latest `part-3-relay-infra`
(main + iPhone companion + real-mode wiring + root domain) merged with
`demo-deploy-fixes`. `make test` is green on it (relay 343 passed). v1's open
bring-up items in `TODO.md` §1-3 (real Gemini, Tiger, deploy, hardware) are
**still open** and are folded into Part 3's and Part 2's READMEs.

---

## 2. End-to-end flow (the M3 demo)

```
PORTAL (supervisor, browser)              RELAY                               LENS (worker)
upload SOP-150.pdf ──────────────────▶ POST /v1/materials
                                        background: extract ▶ convert ▶ verify_step ▶ render diagrams
review: source | step | lens preview ◀─ GET /v1/drafts/...
edit step 3, approve diagram 2 ──────▶ PUT .../steps/{label}  (re-verified on save)
approve ─────────────────────────────▶ POST .../approve ▶ publish: documents + chunks + embeddings
                                                                               boot ▶ POST /v1/devices/pair
type pair code 4F7K from the lens ───▶ POST /v1/devices/claim                  lens shows "Pair code 4F7K"
assign SOP-150 to "Bay 3" ───────────▶ POST /v1/assignments
                                        GET /v1/assignments/next ◀──────────── polled every 10 s in IDLE
                                                                               "Task ready: Pump seal swap. Nod twice to start"
                                                                               nod nod ▶ STEP 1/6
                                        POST /v1/progress ◀────────────────── step_started
                                                                               nod nod, "show diagram" ▶ /v1/ask (command fast path)
                                        GET /v1/diagrams/{id} ◀─────────────── (prefetched) DIAGRAM screen
                                                                               nod nod, "how tight is the gland nut" ▶ answered, cited
                                                                               nod nod, "next" ▶ STEP 2/6, step_completed
live board: Bay 3, step 2/6, 4 min ◀── GET /v1/progress
```

---

## 3. Hands-free interaction model

### Gestures

| Input | Means | Notes |
|---|---|---|
| **Double nod** (two pitch down-up cycles within 1.2 s) | "I want to talk": opens the mic from any non-listening screen | A single nod is too close to glancing at a bench. Default double; single nod becomes an option only after the field false-positive test |
| **Head shake** (>= 2 yaw reversals within 1 s) | Cancel / back | LISTENING -> previous screen; DIAGRAM or DETAILS -> STEP; answer -> back to STEP or IDLE. Ignored on STEP itself, so a shake never loses the place |
| Silence after speech (800 ms) | Send | No press to send |
| No speech within 3 s of opening | Close mic, send nothing | The false-trigger safety valve: a stray double nod costs 3 s of open mic and zero network |
| 8 s cap | Send what we have | Unchanged from v1 |
| Taps | Everything v1 did | Kept as fallback. Double-tap on root still exits (QA gate) |

Gestures are ignored while THINKING and (except shake) while LISTENING.
Cooldown 1.5 s after any trigger. The detector is suspended while the head is
in sustained motion (walking, bending); see Part 2.

### Voice commands (fast path: no retrieval, no LLM)

Rule-based in `intent.py`, matched only when the **whole utterance** is the
command (so "what's the next step's torque" stays a question):

| Say | `command` | Lens does (locally) |
|---|---|---|
| "next", "done", "next step", "finished", "complete" | `next` | progress `step_completed`, advance; last step -> TASK_DONE |
| "back", "previous", "go back" | `back` | previous step |
| "repeat", "say that again" | `repeat` | re-show current step (outside a task, v1 `repeat` intent is unchanged) |
| "details", "more", "read it" | `details` | STEP_DETAILS |
| "diagram", "show diagram", "picture", "show me" | `diagram` | DIAGRAM, or "No diagram for this step" |
| "pause", "stop task" | `pause` | IDLE, task kept |
| "resume", "continue" | `resume` | back to the current step |
| "exit", "close specs" | `exit` | native exit confirmation |

Anything else goes through v1's pipeline unchanged (question / deviation /
walkthrough), with the current `doc_id` + `step_id` as context.

### Privacy, restated for an always-armed gesture

- The IMU is on while the app is in the foreground. **The mic is not.** It
  opens only on a deliberate double nod or tap, and the lens always shows
  LISTENING while it is open.
- No speech detected -> nothing sent. Speech detected -> in-memory PCM, sent,
  dropped. Never persisted. IMU samples never leave the phone.
- First-run privacy screen gains one line: "Nod twice to talk. The mic closes
  when you stop speaking."

---

## 4. Diagrams on the lens

Platform limits (SDK 0.0.16 `ImageContainerProperty`): **max 4 image
containers per page, each 20-288 px wide and 20-144 px tall**, 4-bit
greyscale, filled with `updateImageRawData` after the container exists. Lit
pixels glow green; black is transparent. BLE is 10-30 KB/s.

Decisions:

- **Canvas: 576 x 144**, sent as two 288 x 144 tiles side by side, under a
  40 px header and over a 48 px caption/hint footer. A 576 x 288 four-tile
  "full screen" mode is a stretch goal, not v2 scope.
- **Two sources.** (a) `crop`: a figure from the uploaded material, cropped to
  the region the step needs. (b) `schematic`: a small JSON diagram spec
  (lines, arrows, rects, circles, numbered callouts, short labels) generated
  from the material when it describes a layout (star torque order, valve
  positions) but has no usable figure. Rendered server-side with Pillow.
- **Rendering is the relay's job**, not the WebView's: greyscale, autocontrast,
  invert light-background scans (white paper must become black or the whole
  tile glows), resize to fit, dither to 16 levels. Labels drawn at a size that
  survives the lens (start at 14 px cap height; Part 1 confirms on hardware).
- **Verified like text.** Every number+unit in a schematic label must appear in
  the step's source quotes (same rule as `verify.py`). Every diagram is shown to
  the supervisor *exactly as the lens will render it* and is approved
  separately from the step text. Unapproved diagrams are never sent.
- **Prefetched.** When a step is shown, the app fetches the current and next
  step's diagrams in the background. "Show diagram" should never wait on the
  network.
- **Layout change = page rebuild.** v1 never called `rebuildPageContainer`.
  v2 calls it exactly when switching between the text layout and the diagram
  layout, never for content changes.
- **Byte format is the day-one unknown.** `imageData` takes "grayscale bytes";
  the result enum has `imageToGray4Failed`, so the host may accept an encoded
  image and convert it. Part 2 proves which (PNG bytes vs raw packed 4-bit vs
  8-bit grey) in the simulator on day one and announces it; Part 4 renders
  exactly that. No guessing.

---

## 5. The frozen contract v2

v2 is **additive**: every v1 field keeps its meaning, so the iPhone companion
and v1 tests keep working. Any change needs agreement from Parts 1-5.

### TypeScript (`app/src/types.ts`, Part 1)

```ts
export type Intent = 'question' | 'walkthrough' | 'deviation' | 'repeat' | 'command' | 'unknown';
export type Outcome = 'answered' | 'not_found' | 'logged' | 'clarify' | 'command' | 'error';
export type Command = 'next' | 'back' | 'repeat' | 'details' | 'diagram' | 'pause' | 'resume' | 'exit';

export interface Citation { chunk_id: string; doc_id: string; revision: string; section: string; quote: string; }
export interface Diagram { diagram_id: string; width: number; height: number; alt: string; }
export interface Step {
  step_id: string; label: string; glance: string; body: string;
  warning?: string | null;     // <= 80 chars, ASCII, shown on the step screen
  checkpoint?: string | null;  // <= 60 chars, e.g. "0.20 mm gauge must not enter"
  diagram?: Diagram | null;    // only approved diagrams are ever sent
}
export interface Walkthrough {
  doc_id: string; revision: string; title: string; total: number; index: number; steps: Step[];
  assignment_id?: string | null;
}
export interface Latency { stt: number; embed: number; retrieve: number; generate: number; verify: number; total: number; }

export interface AskRequest {
  session_id: string;
  audio?: { format: 'pcm_s16le'; sample_rate: 16000; channels: 1; data_b64: string };
  text?: string | null;
  revision?: string | null;
  context?: { doc_id: string | null; step_id: string | null; assignment_id?: string | null };
}

export interface AskResponse {
  trace_id: string; transcript: string; intent: Intent; outcome: Outcome;
  glance: string; body: string; source: string; citations: Citation[]; verified: boolean;
  walkthrough: Walkthrough | null; latency_ms: Latency;
  command?: Command | null;           // set iff outcome === 'command'
  needs_clarification?: boolean;      // the relay already sends it (TODO.md §4)
  error?: { code: string; message: string };
}

// Device + task routes
export interface Pairing { device_id: string; device_token: string; pair_code: string; claimed: boolean; worker_name: string | null; }
export interface Assignment { assignment_id: string; walkthrough: Walkthrough; assigned_at: string; }
export type ProgressKind = 'task_started' | 'step_started' | 'step_completed' | 'task_paused' | 'task_completed';
export interface ProgressEvent { assignment_id: string; step_id: string | null; kind: ProgressKind; ts: number; }
export interface DiagramImage {
  diagram_id: string;
  tiles: { slot: 0 | 1; width: number; height: number; image: string /* base64, format per §4 */ }[];
}
```

`outcome: 'command'` carries `verified: false` and empty
`glance`/`body`/`citations`, and is **never rendered as text**: the lens only
acts on `command`.

### Routes

```
# lens (device token as `authorization: Bearer <device_token>`, except pair)
POST /v1/devices/pair        { session_id }                       -> Pairing
GET  /v1/devices/me                                               -> Pairing          # polled until claimed
GET  /v1/assignments/next                                         -> Assignment | 204
POST /v1/progress            { events: ProgressEvent[] }          -> { accepted: n }  # batched; idempotent on (assignment_id, step_id, kind, ts)
GET  /v1/diagrams/{diagram_id}                                    -> DiagramImage     # approved diagrams only
POST /v1/ask                 (v1, + command fast path, + assignment context)

# portal (`authorization: Bearer <PORTAL_TOKEN>`)
POST /v1/materials           multipart: file, doc_id, title, revision  -> { material_id, status: 'converting' }
GET  /v1/materials/{id}                                           -> { status: converting|ready|failed, error?, doc_id, revision }
GET  /v1/materials/{id}/text                                      -> MaterialText     # what the converter read, for review
GET  /v1/drafts/{doc_id}/{revision}                               -> ProcedureDraft
PUT  /v1/drafts/{doc_id}/{revision}/steps/{label}  DraftStepEdit  -> DraftStep        # re-verified on every save
POST /v1/drafts/{doc_id}/{revision}/diagrams/{diagram_id}/approve -> { ok }
POST /v1/drafts/{doc_id}/{revision}/approve                       -> { doc_id, revision, steps }  # 409 if any step fails verify
GET  /v1/diagrams/{diagram_id}/preview.png                        -> image/png        # lens-exact render, for the portal
POST /v1/devices/claim       { pair_code, worker_name }           -> Pairing
GET  /v1/devices                                                  -> Pairing[]        # device_token omitted
POST /v1/assignments         { device_id, doc_id, revision? }     -> Assignment
GET  /v1/progress?since=     -> [{ device_id, worker_name, assignment_id, doc_id, title, step_index, total, kind, ts }]

# unchanged v1
GET /v1/health, POST /v1/deviation, GET /v1/procedures, GET /v1/procedures/{doc_id}/steps, POST /v1/ingest
```

The portal polls `/v1/progress` every 3 s. No websockets.

### Server-side shapes (`schemas.py`, Part 3; consumed by Parts 4 and 5)

```python
class PageText(BaseModel): page: int; text: str           # verbatim markdown of that page
class Figure(BaseModel): figure_id: str; page: int; bbox: tuple[float, float, float, float]; caption: str  # bbox 0..1

class MaterialText(BaseModel):          # extract() output; shown to the supervisor for review
    material_id: str
    pages: list[PageText]
    figures: list[Figure]

class DiagramElement(BaseModel):        # schematic primitives on the 576x144 canvas
    type: Literal['line', 'arrow', 'rect', 'circle', 'text', 'callout']
    x: int; y: int; x2: int | None = None; y2: int | None = None; r: int | None = None
    label: str | None = None            # <= 12 chars, ASCII

class DiagramSpec(BaseModel):
    kind: Literal['crop', 'schematic']
    figure_id: str | None = None        # crop
    bbox: tuple[float, float, float, float] | None = None  # crop, within the figure's page
    elements: list[DiagramElement] = [] # schematic, <= 40
    alt: str                            # <= 80 chars, also the lens caption

class DraftStep(BaseModel):
    label: str; glance: str; body: str  # same caps as v1 Step
    warning: str | None = None; checkpoint: str | None = None
    quotes: list[str]                   # verbatim from MaterialText; the support for every claim
    diagram: DiagramSpec | None = None
    diagram_id: str | None = None       # set after render
    diagram_approved: bool = False
    verify: VerifyResult                # v1 shape

class ProcedureDraft(BaseModel):
    doc_id: str; revision: str; title: str; material_id: str
    status: Literal['converting', 'ready', 'failed', 'approved']
    steps: list[DraftStep]
    warnings: list[str] = []            # document-level warnings, published as one chunk each
```

### Pipeline interfaces v2 (`pipeline/__init__.py`: Part 3 defines, Part 4 implements)

```python
class Converter(Protocol):
    async def extract(self, data: bytes, mime: str, material_id: str) -> MaterialText: ...
    async def convert(self, text: MaterialText, doc_id: str, revision: str, title: str) -> ProcedureDraft: ...

def verify_step(step: DraftStep, text: MaterialText) -> VerifyResult: ...   # sync, no LLM

class DiagramRenderer(Protocol):
    def render(self, spec: DiagramSpec, page_image: bytes | None) -> list[bytes]: ...  # 1-2 tiles, lens format
    def preview_png(self, tiles: list[bytes]) -> bytes: ...
    def page_image(self, data: bytes, mime: str, page: int) -> bytes: ...   # PNG of one page, for crops

def classify_intent(transcript: str) -> Intent         # v1, + 'command'
def parse_command(transcript: str) -> Command | None   # whole-utterance match only
```

---

## 6. Milestones

| M | Done when | Owners |
|---|---|---|
| **M0** (day 1) | `v2-scaffold-app` + `v2-scaffold-relay` tags pushed with contract v2. Image byte format proven in the simulator and announced. Raw IMU recordings of nod / shake / bench work / walking captured on real glasses | 1, 3, 2 |
| **M1** | Simulator, `VITE_MOCK=1`: double nod (IMU replay) -> LISTENING -> silence -> THINKING -> answer, no tap anywhere | 1, 2 |
| **M2** | Simulator: assigned mock task, voice "next" x2, "show diagram" renders a 576x144 diagram from the mock relay, shake returns to the step | 1, 2, 3 |
| **M3** | Real relay: synthetic PDF uploaded in the portal -> draft -> edit -> approve -> claim device -> assign -> the simulator receives it and steps through by voice; the portal board shows progress | 3, 4, 5 |
| **M4** | Real glasses: double-nod detection >= 95 %, <= 1 false trigger per 30 min of scripted bench work; diagram legible on the lens; v1 hardware checks from `TODO.md` §3 | 1, 2 |
| **M5** | Pitch numbers: conversion grounding (0 unverified steps publishable), nod -> LISTENING < 300 ms, "next" p50 < 1.2 s end-of-speech -> new step, answer p50 <= 3 s (v1 target) | all |

## 7. Merge protocol (same as v1)

1. Never commit to `main`. Open a PR from your branch when your milestone is green.
2. Commit and push to your own branch constantly. Small commits.
3. Two scaffold tags are the only cross-branch dependency in the first hours:
   `v2-scaffold-app` (Part 1) and `v2-scaffold-relay` (Part 3).
   `git fetch --tags && git merge v2-scaffold-relay` (or `v2-scaffold-app`).
4. Stay inside **Files you own**. Need a change elsewhere: one line in the
   team channel to the owner.
5. `make test` green at the end of every milestone, including `make test-ios`.
6. Do **not** add `Co-Authored-By: Claude` to commits.

## 8. House rules (every v1 rule still applies)

- Never persist raw audio. IMU samples never leave the phone, except the
  recorded fixtures Part 2 commits for tests (motion only, no audio, no names).
- No secrets in the app bundle. `PORTAL_TOKEN`, the device-token secret and all
  provider keys live in the relay's `.env` only.
- **Synthetic material only.** The portal will accept any file, but until a
  data-handling review we upload only the synthetic demo materials in
  `corpus/materials/`. Never a real employer document.
- Nothing reaches the lens unless it is quoted, verified and human-approved.
  When unsure, the step fails verification and the supervisor fixes it.
- Do not touch firmware or modify the loaned glasses.
