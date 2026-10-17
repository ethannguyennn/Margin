# Part 3 — Relay Service, Observability & Deploy

**Branch:** `part-3-relay-infra`
**Owns:** the FastAPI service that everything else plugs into, the public
HTTPS origin, Sentry on the server, and the repo's build tooling. You are the
integration point: Parts 4 and 5 fill modules you define, Part 2 calls routes
you expose.

**Milestones:** M0 (repo tooling), M2 (mock relay end to end), M6
(observability + deploy). You publish the `scaffold-relay` tag that Parts 4
and 5 depend on — do that first.

---

## 1. Files you own

```
Makefile                               # dev-relay, dev-app, sim, test, seed, latency, eval
.env.example                           # every env var, no real values
relay/pyproject.toml
relay/src/margin_relay/main.py         # app factory, CORS, router mount, Sentry init
relay/src/margin_relay/config.py       # pydantic-settings
relay/src/margin_relay/schemas.py      # pydantic models of the contract (SHARED)
relay/src/margin_relay/obs.py          # span helper + events writer interface
relay/src/margin_relay/routes/         # ask.py, procedures.py, deviation.py, health.py, ingest.py
relay/src/margin_relay/pipeline/mock.py  # mock implementations of the pipeline
relay/tests/test_routes.py, relay/tests/test_cors.py
deploy/docker-compose.yml
deploy/Caddyfile
```

## 2. Files you must NOT touch

`relay/src/margin_relay/pipeline/{transcribe,intent,retrieve,generate,verify,sanitize}.py`
(Part 4), `relay/src/margin_relay/db.py`, `relay/src/margin_relay/notify/`,
`db/`, `corpus/`, `eval/` (Part 5), all of `app/` (Parts 1 and 2), and
**`main`**.

---

## 3. Config (`config.py` + `.env.example`)

pydantic-settings, one class, every value read from env. **No hardcoded model
IDs** — look up current Gemini model IDs in Google's docs and leave the env
vars empty in `.env.example`.

```
# Gemini
GEMINI_API_KEY=
GEMINI_MODEL_GENERATE=        # fast, current Flash-class model
GEMINI_MODEL_TRANSCRIBE=      # same family is fine (audio input)
GEMINI_MODEL_EMBED=           # embedding model
EMBED_DIM=768                 # request 768 via output_dimensionality if supported; VERIFY

# Tiger Cloud (Postgres)
DATABASE_URL=
DATABASE_URL_FORK=            # optional: fork with SOP rev D (stretch)

# Sentry
SENTRY_DSN_RELAY=
SENTRY_DSN_APP=               # public DSN, goes into the app build env

# Notifier (Part 5)
NOTIFIER=console              # console | photon
PHOTON_API_KEY=
SUPERVISOR_ADDRESS=

# Retrieval thresholds (Part 4)
NOT_FOUND_MIN_SIM=
NOT_FOUND_MIN_RRF=

# Server
PUBLIC_ORIGIN=https://margin.<our-domain>   # must equal the app.json whitelist entry
ALLOWED_ORIGINS=              # origins the WebView sends; VERIFY on device
MOCK_MODE=0
MAX_AUDIO_SECONDS=8
ADMIN_TOKEN=
```

**Never commit a real key.** `.env` is gitignored; `.env.example` has keys with
empty values only.

## 4. CORS — get this right on day one or the demo dies

The WebView is a browser. It sends real `Origin` headers and does real
preflights.

- Allow the WebView origin(s) from `ALLOWED_ORIGINS`.
  **Verify the actual origin on device** (relay logs / devtools) — do not
  guess it. Log every rejected origin at WARN so a mismatch is obvious in 10
  seconds instead of an hour.
- Allowed headers must include `content-type`, `sentry-trace`, `baggage`,
  `x-session-id`.
- `OPTIONS` must return 2xx on every route.
- Separately, the Even network layer requires `app.json` to whitelist the
  **full origin** (`https://margin.<domain>`) — no wildcards, no bare hosts.
  Part 1 owns `app.json`; give them the exact string.

## 5. The frozen contract (you own the server-side source of truth)

`schemas.py` is the pydantic mirror of this. Parts 4 and 5 import from it and
never redefine it. Any change needs agreement from Parts 1-5 in the channel.

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

Exactly one of `audio` / `text`. `text` bypasses STT — every test and
`make eval` uses it. Reject audio longer than `MAX_AUDIO_SECONDS` with
`bad_request`.

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
- `glance` <= 60 chars, `body` <= 450 chars, both sanitized server-side
  (Part 4's `sanitize.py`). **Enforce the length caps in `schemas.py`** — the
  lens truncates ugly, so fail loudly in dev instead.
- `walkthrough` present only when `intent == walkthrough`:
  `{ doc_id, revision, title, total, index, steps: [ { step_id, label, glance, body } ] }`
  All steps at once; the app navigates locally for zero-latency swiping.
- `not_found`: `glance = "Not in approved SOPs"`,
  `body = "No matching procedure. Try rephrasing or ask your supervisor."`,
  `citations = []`, `verified = false`.
- Error: `{ trace_id, outcome: "error", error: { code: "stt_failed|db_down|llm_timeout|bad_request", message } }`
  with the matching HTTP status.
- **Every response carries `trace_id`, including errors.**

### Other routes

```
GET  /v1/health                               -> { ok, mock, db, version }
POST /v1/deviation  { session_id, text, doc_id, step_id }  -> { deviation_id, notified }
GET  /v1/procedures                           -> [ { doc_id, title, revision, status } ]
GET  /v1/procedures/{doc_id}/steps?revision=  -> ordered steps
POST /v1/ingest     (ADMIN_TOKEN)             -> re-ingest /corpus
```

`/v1/deviation` is normally called internally by `/v1/ask` when
`intent == deviation`; keep the route for direct use and for the demo.

## 6. Pipeline interfaces you define (Parts 4 and 5 implement)

Put these in `pipeline/__init__.py` as `Protocol`s, with working mock
implementations in `pipeline/mock.py`. `/v1/ask` is one function that calls
these in order and times each one. **This is the only file that orchestrates;
nobody else owns the request flow.**

```python
class Transcriber(Protocol):
    async def transcribe(self, pcm: bytes, sample_rate: int) -> str: ...

def classify_intent(transcript: str) -> Intent: ...                 # Part 4, sync, rule-based

class Retriever(Protocol):
    async def retrieve(self, query: str, revision: str | None) -> RetrievalResult: ...
    # RetrievalResult: chunks: list[Chunk], best_sim: float, best_rrf: float
    async def steps_for(self, doc_id: str, revision: str | None) -> list[Step]: ...

class Generator(Protocol):
    async def generate(self, query: str, chunks: list[Chunk]) -> Draft: ...
    # Draft: answerable, needs_clarification, glance, body, citations[{chunk_id, quote}]

def verify(draft: Draft, chunks: list[Chunk]) -> VerifyResult: ...  # Part 4, sync, no LLM

def sanitize(text: str) -> str: ...                                 # Part 4, sync

class Notifier(Protocol):                                           # Part 5
    async def notify(self, deviation_id: str, text: str) -> bool: ...
```

Resolution is one factory in `main.py`: `MOCK_MODE=1` returns the mocks,
`MOCK_MODE=0` returns the real ones. Import the real modules lazily inside the
factory so the service still boots with `MOCK_MODE=1` before Parts 4 and 5
have pushed anything:

```python
try:
    from .pipeline import retrieve as real_retrieve
except ImportError:
    real_retrieve = None
```

Same trick for `db.py` (Part 5): with no `db` module, `/v1/health` reports
`"db": "mock"` and still returns `ok: true`.

### `/v1/ask` flow (yours)

1. Resolve transcript: `text` if given, else `transcribe(audio)`.
2. `classify_intent`.
3. `deviation` -> write deviation + notify -> `outcome: "logged"`.
   `repeat` -> re-send the session's last answer from memory, no pipeline call.
   `walkthrough` -> retrieve, take the top chunk's `doc_id`, return
   `steps_for(...)`.
   `question` -> retrieve -> below both thresholds? `not_found` **without
   calling the LLM** -> else generate -> verify.
4. Verify fails: retry generation **once** with the failure reason; fails
   again -> `not_found`. **Never return unverified text as an answer.**
5. Sanitize `glance` and `body`. Build `source` as
   `"{doc_id} Sec {section} rev {revision}"` from the first citation.
6. Write one `events` row (Part 5's writer) and return.

Wrap each stage in a Sentry span **and** record its milliseconds into
`latency_ms`. One timing helper, used six times.

## 7. Observability

- `sentry-sdk` with the FastAPI integration, tracing and logs on.
- Spans named exactly `stt`, `embed`, `retrieve`, `generate`, `verify` so they
  line up with the app's `capture` / `upload` / `render`.
- Continue the app's trace from the `sentry-trace` and `baggage` headers —
  that is why CORS must allow them. One unbroken trace from press to glance is
  a judging criterion, not a nice-to-have.
- One `events` row per request with the `latency_ms` JSON (Part 5 owns the
  table and the writer; you own calling it).
- `make latency` prints p50/p95 per stage from `events`. Our pitch number is
  **p50 end-of-speech to glance on the lens, target <= 3 s**.
- Optional, last: `/v1/sentry-tunnel` so the app only needs one whitelisted
  origin.

## 8. Deploy

- Relay in Docker on a **Vultr** VM. `deploy/docker-compose.yml` runs relay +
  Caddy; Caddy terminates TLS for `margin.<domain>` (GoDaddy Registry domain,
  DNS pointed at the VM).
- **Deploy early, on the real domain, while it is still just the mock relay.**
  Venue Wi-Fi often isolates clients, so a public HTTPS origin is the fallback
  for the whole team. A phone hotspot is the backup plan.
- Local dev: `make dev-relay` (uvicorn reload) + `make dev-app`. Hardware
  sideload needs a LAN IP, never `localhost`.
- Health check in compose so a crashed relay restarts itself. It is a
  hackathon; the demo is at noon.

## 9. Makefile targets (contract with the rest of the team)

```
make dev-relay   # uvicorn, reload, MOCK_MODE from .env
make dev-app     # cd app && npm run dev
make sim         # even simulator
make test        # pytest relay/tests + npm test in app  (must stay green)
make seed        # python db/seed.py            (Part 5)
make eval        # python eval/run_eval.py      (Part 5)
make latency     # p50/p95 per stage from events
make deploy      # docker compose up -d --build on the VM
```

## 10. Build order

1. `pyproject.toml`, `config.py`, `schemas.py`, `main.py` with `/v1/health`,
   CORS, Sentry init, and `pipeline/mock.py`. Commit, then
   `git tag scaffold-relay && git push origin part-3-relay-infra --tags` and
   **announce it.** Parts 4 and 5 are waiting on this; nothing else of yours
   matters until it is pushed.
2. `/v1/ask` with `MOCK_MODE=1` returning the fixture set Part 2 mocks on the
   app side (answered / walkthrough / not_found / logged / error). Tell Part 2.
3. Makefile + `.env.example`.
4. Docker + Caddy + domain live with the mock relay.
5. Spans, `latency_ms` timing, `events` write, `make latency`.
6. Real-mode factory wiring once Parts 4 and 5 land.

## 11. Acceptance

- **M2 done:** Part 2's client in the simulator renders a response from your
  running relay; a deliberately failing relay produces the app's ERROR screen.
- [ ] Preflight `OPTIONS /v1/ask` from the real device origin returns 2xx.
- [ ] `trace_id` present on every response, success and error.
- [ ] `MOCK_MODE=1` boots with no DB, no Gemini key and no pipeline modules.
- [ ] A relay span tree appears in Sentry under the same trace as the app's.
- [ ] `glance`/`body` over the caps raise in dev rather than silently truncate.
- [ ] `https://margin.<domain>/v1/health` answers from a phone on cellular.
- [ ] `make test` green.

## 12. Merge protocol (read once, it is short)

1. **Never commit to `main`.** `main` stays empty until the integration merge.
2. Commit and push to your own branch constantly. Small commits.
3. You publish `scaffold-relay` in the first hour; Part 1 publishes
   `scaffold-app`.
4. Stay inside **Files you own**. If you need a change in someone else's file,
   post a one-line request in the channel; do not edit it.
5. Integration order into `main`: 1, 3, 2, 4, 5. You are second in, so keep
   your branch mergeable at all times.
6. Do **not** add `Co-Authored-By: Claude` to commits.

## 13. House rules

- **All third-party keys live here and only here.** The app bundle gets
  nothing but the public Sentry DSN.
- Never persist raw audio. Process the PCM in memory, store transcript text
  and metrics only.
- Synthetic SOPs only.
- `make test` green at the end of every milestone.
