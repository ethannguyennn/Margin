# Specs

**Hands-free work instructions on smart glasses. Every answer is quoted from your own approved SOPs, or it doesn't show up at all.**

A frontline worker nods twice, asks a question out loud, and sees the answer on their Even Realities G2 lens. The answer is a short quote from the employer's approved procedure, with its section cited. If the SOPs don't contain the answer, the lens says *"Not in your SOPs. Ask your manager to add it."* instead of guessing, so the gap reaches the person who can close it.

---

## Table of contents

1. [The problem](#the-problem)
2. [Our solution](#our-solution)
3. [How it works](#how-it-works)
4. [The trust layer](#the-trust-layer)
5. [Sponsor utilization](#sponsor-utilization)
6. [Architecture](#architecture)
7. [Repository layout](#repository-layout)
8. [Getting started](#getting-started)
9. [Testing and evaluation](#testing-and-evaluation)
10. [Deployment](#deployment)
11. [Status and known limitations](#status-and-known-limitations)
12. [Ground rules](#ground-rules)

---

## The problem

Standard operating procedures (SOPs) are how work gets done the right way: in a café, on a production line, or in a maintenance bay. In practice they live in binders, PDFs and shared drives. The people who need them most have their hands full.

- **Hands are busy.** A barista steaming milk or a tech holding a pump seal can't scroll a PDF. They guess, or they stop work to go and look.
- **Asking a chatbot is risky.** General LLM assistants confidently invent numbers. A wrong temperature, torque value or sanitizer concentration is a safety, quality or compliance failure, not a typo.
- **Supervisors can't see the floor.** Once a task is assigned there's no signal about which step someone is on or where they got stuck.
- **Authoring is the bottleneck.** Turning a paper SOP into something interactive usually means a developer rewriting it by hand.

## Our solution

Specs puts the employer's own procedures on the worker's glasses, and puts a deterministic trust layer between the language model and the lens.

| For the worker (glasses + phone) | For the supervisor (web portal) |
|---|---|
| **Double nod** opens the mic. Silence sends. No taps needed. | **Upload** a PDF, DOCX, text file or a phone photo of a paper SOP. |
| Ask in your own words: *"how hot should the milk be?"* | Specs **converts** it into a step-by-step procedure with diagrams, and never invents a value. |
| Open a procedure by voice: *"bring up the closing checklist"*. | **Review** the source and the lens preview side by side, edit, then **approve**. |
| Step through it hands-free: *"next"*, *"go back"*, *"show me the picture"*. | **Pair** glasses with a code shown on the lens, and **assign** procedures to a station. |
| Ask a follow-up mid-step and land back on the same step. | Follow a **live progress board**: who is on which step, and for how long. |
| Ask something ambiguous and the lens asks *"Which drink?"*, offering only options the SOPs already contain. | Read deviation reports workers file from the phone. |
| Ask something no SOP covers and get pointed to your manager, never a guess. | **Test** the workspace's SOPs in a browser **glasses simulator** before anyone puts on a headset. |
| The phone's **Lens** tab mirrors the glasses live, or runs the same simulator when no glasses are connected. | |

The core promise: **nothing reaches the lens unless it is quoted from the employer's material, passes the deterministic verifier, and was approved by a human.**

## How it works

### The worker loop

```
 nod nod ──▶ mic opens ──▶ speech ──▶ 800 ms silence ──▶ POST /v1/ask (audio)
                                                            │
        ┌───────────────────────────────────────────────────┘
        ▼
  Gemini STT ──▶ intent: command | walkthrough | question
                       │            │              │
            "next", "back",   open an SOP at    hybrid retrieval (pgvector + full-text, RRF)
            "show picture"    the asked section  ──▶ relevance gate (refuse off-topic)
            (fast path,       scoped to that     ──▶ Gemini drafts a cited answer
             no LLM)          section group      ──▶ deterministic verifier
                                                 ──▶ ANSWERED  |  NOT FOUND  |  CLARIFY
        ┌───────────────────────────────────────────────────┘
        ▼
  lens: glance + paginated body + reference image (288×144 greyscale)
  phone: full answer, citations, walkthrough, latency, trace id
```

- **Gestures:** double nod = talk, head shake = cancel/back (ignored on a step, so you never lose your place), and temple taps remain as a fallback. If no speech arrives within 3 s, the mic closes and nothing is sent, so a stray nod costs nothing.
- **Clarify, don't guess:** if a question is ambiguous ("how many pumps of syrup?"), the relay returns 2–3 options taken from section headings it actually retrieved. The worker answers ("the cappuccino"), and the relay combines that with the original question.
- **Scoped walkthroughs:** "walk me through a cappuccino" opens the SOP at section 3.2 and finishes at the end of that section group, not the end of the document.
- **Not found → manager:** when nothing approved covers a question, the lens shows *"Not in your SOPs. Ask your manager to add it."* and the phone tells the worker to contact their manager so the procedure can be added in the portal. The gap becomes a request for a new SOP instead of a guess.
- **Reference pictures:** each illustration is pinned to an exact SOP revision and source anchor (`corpus/illustrations.json`). The model can only pick an image that belongs to a chunk it cited.

### The supervisor loop

```
PORTAL                                 RELAY                                       LENS
upload SOP-150.pdf ───────────────▶ POST /v1/materials
                                    extract ▶ convert ▶ verify_step ▶ render diagrams
review source | steps | preview ◀── GET /v1/drafts/...
approve ──────────────────────────▶ publish: documents + chunks + embeddings
                                                                   boot ▶ "Pair code 4F7K"
type 4F7K ────────────────────────▶ POST /v1/devices/claim
assign to "Bay 3" ────────────────▶ POST /v1/assignments ◀──────── polled while idle
                                                                   "Task ready. Nod twice to start"
live board ◀──────────────────────  GET /v1/progress ◀──────────── step_started / step_completed
```

### The glasses simulator

Both web apps include a browser preview of the G2 lens (576×288). It uses the app's real lens controller, screen renderer and container positions.

- **Portal → Simulator** (`/portal/#simulator`): a supervisor asks questions and runs commands against their own workspace's SOPs through `/v1/simulator/ask`, with portal auth. Diagram tiles load only from that workspace's approved, effective procedures. No fake device, assignment or progress event is created.
- **Live glasses** in either web app: select a glasses device in the same workspace to follow its acknowledged text, reference images and two diagram tiles. Install/open Specs 0.4.4 on the G2 and keep it in the foreground. The viewer marks paused or disconnected sources offline after 12 seconds. **Browser simulation** remains a separate mode; its controls do not drive the physical glasses.
- **Worker app → Lens tab** (`/app/#/lens`): the live viewer by default, with browser simulation available beside it. Inside the connected Even app, the Lens tab mirrors the local display directly.

Setup, packaging commands, authentication boundaries and hardware-test limitations:
[`docs/handoffs/LIVE-DISPLAY-SYNC.md`](docs/handoffs/LIVE-DISPLAY-SYNC.md).

Screenshots, reproduction commands, and which results are mock versus hardware evidence: [`app/tests/evidence/browser-simulator/README.md`](app/tests/evidence/browser-simulator/README.md).

## The trust layer

The verifier (`relay/src/specs_relay/pipeline/verify.py`) uses no LLM. A drafted answer reaches the lens only if:

1. it is answerable, has at least one citation, and fits the lens size limits;
2. every cited chunk was actually retrieved for this question;
3. every quote appears in its chunk after normalising case, whitespace and punctuation. Fuzzy matching tolerates spacing noise, but a quote with different digits fails;
4. every number+unit and part code in the answer (`165 °F`, `M5`, `SOP-131`) appears in a cited quote with the same unit.

Around the verifier:

- **Relevance gate:** retrieval similarity below a measured threshold (`NOT_FOUND_MIN_SIM=0.68`) refuses before the model is called. On the demo bank, off-topic prompts score 0.55–0.64 and every answerable question scores ≥ 0.72.
- **Never truncate a warning:** a warning, value or acceptance limit is never cut to fit the lens. Verification fails instead.
- **Authoring gets the same rules:** converted drafts go through `verify_step` and human approval before they can be published.

## Sponsor utilization

| Sponsor | What we use | Where it matters |
|---|---|---|
| **[Even Realities](https://www.evenrealities.com/)** (G2 glasses + Even Hub) | The whole worker experience is an Even Hub app (`app/`): lens text containers, 4-bit greyscale image containers, the glasses microphone, temple gestures and the **IMU** for nod and shake detection. The phone companion screen runs in the Even app's WebView. `evenhub-simulator` drives our smoke tests, and our own browser simulator reuses the lens renderer so supervisors can preview the G2 display without hardware. | Hands-free is the product. Our nod detector runs on the G2's gravity-normalised accelerometer and was tuned on real glasses, BLE bursts included. Answers, steps and reference images are laid out for the 576×144 lens. |
| **[Google Gemini](https://ai.google.dev/)** | Four roles, each configured by its own env var: **speech-to-text** with a domain vocabulary prompt (`pipeline/transcribe.py`), **embeddings** at 768 dimensions for retrieval, **structured cited answer generation** (`pipeline/generate.py`), and **multimodal conversion** of uploaded PDFs, DOCX files and photos into draft procedures (`relay/src/specs_relay/convert/`). | Gemini drafts. The deterministic verifier decides. Structured output gives us typed citations to check. Transient 429/5xx errors get one retry within the latency budget, and quota errors show the lens-safe message *"Busy, try again"*. |
| **[Tiger Data](https://www.tigerdata.com/)** (Tiger Cloud: Postgres + pgvector + TimescaleDB) | One database for everything: SOP chunks with **pgvector** embeddings and a generated **`tsvector`**, fused by reciprocal-rank fusion for hybrid retrieval; **hypertables** for `events` (per-stage ask latency) and `progress` (the live board); plus devices, assignments, drafts and uploaded source files (`db/migrations/`). Optional **zero-copy fork** for previewing a new SOP revision (`DATABASE_URL_FORK`, `ENABLE_REVISION_FORK`). | Hybrid search catches both "how hot is the milk" (semantic) and "SOP-210 4.2" (lexical). `make latency` reports p50/p95 per stage straight from the hypertable. |
| **[Sentry](https://sentry.io/)** | Relay and app SDKs, with **one distributed trace per ask**: lens gesture → capture → upload → STT → retrieval → generation → verification → render. Each stage is a span. A same-origin tunnel (`routes/sentry_tunnel.py`) lets the WebView report through the relay. Raw audio is filtered from logs. | Debugging a voice loop across glasses, phone, relay and Gemini needs one timeline. The phone screen shows the trace id with each answer. |
| **[Vultr](https://www.vultr.com/)** | One Cloud Compute VM running the relay and Caddy (automatic TLS) via Docker Compose (`deploy/`), behind `getyourassto.work`. `make deploy-remote` fast-forwards a clean `main` checkout on the VM and rebuilds. | Small enough for 1 vCPU / 1–2 GB. One origin serves the API at `/v1/`, the employer portal at `/portal/` and the worker companion with its lens simulator at `/app/`. |

*Photon (supervisor notifications) is stubbed behind `NOTIFIER=photon` but not enabled, because its API access hasn't been verified. The console notifier is the default.*

## Architecture

```
┌──────────────────────────┐      HTTPS /v1        ┌──────────────────────────────────┐
│ Even Hub app  (app/)     │ ────────────────────▶ │ Relay  (relay/, FastAPI)         │
│  lens: state machine,    │                       │  ask orchestrator, intents,      │
│        screens, IMU      │ ◀──────────────────── │  retrieval, gate, generation,    │
│  phone: React companion  │   answers, steps,     │  verifier, conversion jobs,      │
└──────────────────────────┘   diagram tiles       │  devices, assignments, progress  │
                                                   └───────┬───────────────┬──────────┘
┌──────────────────────────┐   same origin /portal/        │               │
│ Employer portal (portal/)│ ─────────────────────────────▶│               │
│  upload, review, approve,│                               ▼               ▼
│  pair, assign, board     │                    Tiger Cloud Postgres    Gemini API
└──────────────────────────┘                    pgvector + Timescale    STT/embed/
                                                                        generate/convert
                         Sentry traces span the app, the relay and every Gemini call
```

- **App:** TypeScript + Vite, built on the official Even Hub template. `src/lens-link.ts` is the only seam between the lens and the phone screen.
- **Relay:** Python 3.11+, FastAPI and pydantic. `MOCK_MODE=1` runs it with no database and no Gemini.
- **Portal:** Vite + vanilla TypeScript. A shared supervisor token is entered at login and never bundled.

## Repository layout

| Path | What's there |
|---|---|
| `app/` | Even Hub app: lens UI (`src/state.ts`, `src/ui/`), motion and gestures (`src/motion/`), audio, API client, phone companion (`src/phone/`) |
| `relay/` | FastAPI relay: routes, ask pipeline (`pipeline/`), conversion (`convert/`), diagram rendering (`diagrams/`), tests |
| `portal/` | Employer portal: library, uploads, draft review, approvals, pairing, assignments, progress board, glasses simulator |
| `db/` | SQL migrations and `seed.py` |
| `corpus/` | Demo SOP bank: 13 fictional *Ember & Oak Coffee* SOPs (SOP-201…300, rev C) covering the register, back of house, espresso, recipes, tea and blended drinks, food, guest service, front of house, equipment, inventory, safety and team policies. Also their 71 figures (`figures/`), the lens reference illustrations, and sample upload materials (`materials/`) |
| `eval/` | Answer-quality eval (`qa.jsonl`, `run_eval.py`), gate calibration (`tune_gate.py`), conversion eval, saved results |
| `deploy/` | Docker Compose, Caddy, relay image, health check, remote deploy |
| `tools/diagnostic/` | Paced live end-to-end harness: synthesized speech through the app's real detector, controller and client |
| `docs/` | Field-test protocol (`field/`), evidence, part handoffs, the [open TODO list](docs/TODO.md) |

## Getting started

**Prerequisites:** Python 3.11+, Node 22.12+, GNU make (`mingw32-make` on Windows). For real mode you also need a Gemini API key and a Postgres instance with pgvector and TimescaleDB (Tiger Cloud).

```sh
cp .env.example .env          # every variable is documented inline; never commit .env
make venv && make install     # relay venv + app and portal npm deps
```

### Run everything on mocks (no keys needed)

```sh
# .env: MOCK_MODE=1, ALLOWED_ORIGINS=http://localhost:5174
make dev-relay                # relay on :8080
make dev-app                  # Even Hub app on :5174 (a browser shows the phone screen)
make sim                      # evenhub-simulator against the dev app (lens view)
make dev-portal               # employer portal, proxies /v1 to the relay
```

### Real mode

```sh
# .env: MOCK_MODE=0, GEMINI_API_KEY, GEMINI_MODEL_*, DATABASE_URL, NOT_FOUND_MIN_SIM/RRF
make seed ARGS=--probe-only   # check the Gemini embedding model and dimension
make seed                     # apply migrations, then chunk + embed corpus/ into Postgres (db/README.md)
make dev-relay
```

### On the glasses

```sh
make pack                     # builds app/specs.ehpk; sideload it through Even Hub
```

The app's relay origin must exactly match the `network` whitelist in `app/app.json`. App-side variables live in `app/.env.example`.

## Testing and evaluation

```sh
make test                     # relay pytest + app tests, typecheck and build + portal tests
make eval                     # 139-case answer-quality bank against a running relay
make eval-conversion          # material → procedure; fails on any fabricated value
make latency                  # p50 / p95 per pipeline stage from the events hypertable
make health URL=https://getyourassto.work
```

**Latest results** (merged `main`, 2026-10-18):

- **Tests:** relay 893 passed, app 626 passed, portal 10 passed. Typecheck and builds are green.
- **Live eval on the deployed relay** (74 cases on the earlier 5-SOP bank, paced; `eval/results/2026-10-18-v3-full-7cdbbc6.json`). The 13-SOP, 139-case bank hasn't had a live run yet:

| Metric | Result |
|---|---|
| Answered correctly | 91.7 % |
| `not_found` recall (off-domain, near-miss, ambiguous) | 100 % |
| `not_found` precision | 93.3 % |
| Citation verification pass rate | 98.3 % |
| Ambiguous → clarify | 12 / 12 |
| Median end-to-end latency | 1.31 s |

A human review of the same saved responses scored 35/36 on the original answerable questions, with zero unverified answers (`eval/results/2026-10-18-v3-reviewed-7cdbbc6.json`).

## Deployment

The relay and Caddy run with Docker Compose on a Vultr VM. Caddy serves both web apps: the admin portal (with its simulator at `/portal/#simulator`) and the worker app (Lens tab at `/app/#/lens`). Full runbook: [`deploy/README.md`](deploy/README.md).

```sh
make deploy-remote VM_HOST=root@<vm-ip>   # fast-forward clean main on the VM, then `make deploy`
make health URL=https://<your-domain>
```

## Status and known limitations

The current open list is [`docs/TODO.md`](docs/TODO.md). In short:

- **Field acceptance is still pending:** two wearers in café noise, 5 SOPs opened by voice, 15 clarifying questions, double-nod hit rate ≥ 95 % and ≤ 1 false trigger per 30 min. Real-glasses runs so far have confirmed double nods, rendered reference images and natural voice commands.
- **Gemini quota:** the shared key is paced at 10 s between live checks. Paid or higher quota hasn't been confirmed.
- **A two-turn clarify case** ("how many pumps of syrup?" → "cappuccino") still refuses safely instead of answering. The refusal is safe, but the case isn't solved yet.
- **Illustrations are generated:** they show fictional demo equipment. Use approved site photographs for real work.

## Ground rules

- Nothing reaches the lens unless it is quoted, verified and approved by a human.
- Never persist raw audio. IMU samples never leave the phone, except committed motion-only test fixtures.
- No secrets in the app bundle. Provider keys live only in the relay's `.env`.
- Synthetic material only: every SOP in `corpus/` is fictional sample data for testing.
