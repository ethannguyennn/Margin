# Part 3 v2 handoff: relay platform, contract, deploy

Branch `part-3-relay-platform`. Tag **`v2-scaffold-relay`** = the commit that contains this
file. Merge it: `git fetch --tags && git merge v2-scaffold-relay`.

## What is done

| Piece | Where |
|---|---|
| Contract v2, server side (BUILD-PLAN-V2 §5), additive | `schemas.py` |
| v2 Protocols: `Converter`, `StepVerifier`, `DiagramRenderer`, `CommandParser`, `ConversionError` | `pipeline/__init__.py` |
| `/v1/ask` command fast path (no retrieval, no LLM) | `routes/ask.py` |
| Portal bearer + device tokens, pair codes, pair rate limit | `auth.py` |
| Conversion job: extract -> convert -> verify_step -> render -> save | `jobs.py` |
| Devices, assignments, progress, diagrams, materials, drafts | `routes/*.py` |
| One walkthrough builder for `/v1/ask` and `/v1/assignments/next` | `routes/common.py` |
| Mock relay for every v2 route, incl. an approved demo diagram (M2) | `pipeline/mock.py` |
| Real-mode factory: Part 4 `parse_command`, `verify_step`, `GeminiConverter`, `DiagramRenderer`; Part 5 `publish_draft` | `main.py` |
| Caddy serves the portal at `/portal/`, 22 MB edge body cap | `deploy/` |
| Deps `python-multipart Pillow pypdf pypdfium2 python-docx`; env vars | `relay/pyproject.toml`, `.env.example`, `config.py` |
| `make dev-portal`, `make test-portal`, `make eval-conversion` | `Makefile` |

## Routes as implemented

| Route | Auth | Success | Errors |
|---|---|---|---|
| `POST /v1/devices/pair` `{session_id}` | open, 10/min/IP | `Pairing` with the token (only time it is shown) | 429 |
| `GET /v1/devices/me` | device | `Pairing` (token echoed back) | 401 unknown token, or unclaimed code expired -> re-pair |
| `GET /v1/assignments/next` | device | `Assignment` | **204** no task |
| `POST /v1/progress` `{events: <=500}` | device | `{accepted: n}` (new rows only) | scoped to the device; never raises |
| `GET /v1/diagrams/{id}` | device | `DiagramImage` (stored tile bytes, base64) | 404 unless approved + effective/pinned |
| `POST /v1/materials` multipart `file, doc_id, title, revision` | portal | **202** `{material_id, status: converting}` | 400 identifiers, 413 size, 415 type (magic bytes, must match the extension) |
| `GET /v1/materials/{id}`, `/text` | portal | `MaterialStatus`, `MaterialText` | 404 |
| `GET /v1/drafts/{doc}/{rev}` | portal | `ProcedureDraft` | 404 |
| `PUT .../steps/{label}` `DraftStepEdit` | portal | `DraftStep`, re-verified | 404, 409 (published / diagram mismatch) |
| `POST .../diagrams/{id}/approve` | portal | `{ok: true}` | 404 not this draft, 409 step not verified |
| `POST .../approve` | portal | `{doc_id, revision, steps: Step[]}` (published steps) | **409** with `detail: [{label, reason}]` |
| `GET /v1/diagrams/{id}/preview.png` | portal | `image/png`, drafts too | 404 |
| `POST /v1/devices/claim` `{pair_code, worker_name}` | portal | `Pairing` with `device_token: ""` | 404 unknown / expired / claimed |
| `GET /v1/devices` | portal | `DeviceInfo[]` (no tokens) | |
| `POST /v1/assignments` `{device_id, doc_id, revision?}` | portal | `Assignment` | 404 unclaimed device / unpublished procedure |
| `GET /v1/progress?since=<ms>` | portal | board rows (Part 5's query, incl. `step_started_at`, `deviations`) | |

Auth runs as a FastAPI dependency, so an unauthenticated caller always gets 401 before any
body validation. Every error is the contract shape `{trace_id, outcome: "error", error: {code,
message}}`; v2 adds a `detail` field (the portal shows it) and the codes `unauthorized`,
`not_found`, `conflict`, `rate_limited`, `payload_too_large`, `unsupported_media_type`.

## Decisions other parts depend on

- **Draft shapes do not enforce caps.** `DraftStep`, `DiagramSpec` and `DiagramElement` accept
  over-cap text; Part 4's `verify_step` reports it as a failing step ("warning is 91 chars; the
  lens limit is 80"). Hard `max_length` there would turn one long Gemini field into a lost
  conversion. Lens-facing `Step.warning` (80), `Step.checkpoint` (60) and `Diagram.alt` (80) are
  hard caps, and approve requires every step to verify.
- **Commands.** `parse_command` runs right after transcription. A command returns
  `outcome: 'command', intent: 'command', command`, `verified: false`, empty glance / body /
  citations, latency STT only, one events row with `intent='command'`. `repeat` is a command only
  when `context.step_id` is set; outside a task "say that again" stays v1 `repeat`.
- **The conversion job re-verifies every step** with `verify_step` (the converter is not the
  authority), renders every spec, and never sets `diagram_approved`.
- **Tiles are served as stored**, base64; the relay never re-encodes. Part 2 proved 8-bit grey
  PNG; Part 4 renders it; the mock renderer emits the same format.
- **Device tokens** are `secrets.token_urlsafe(32)`, stored as SHA-256 only; never logged, never
  returned to the portal. No `DEVICE_TOKEN_SECRET`: nothing is signed.
- **Progress batches** above Part 5's 100-event cap are split; duplicates count 0.
- `/v1/ask` passes `assignment_id=` to `write_event` automatically once the writer accepts it.

## Commands

```
make install            # relay venv deps + npm ci in app/, ios/, portal/
make dev-relay          # MOCK_MODE from .env; mock relay answers every v2 route
make dev-portal         # portal dev server, proxies /v1 to :8080 (needs PORTAL_TOKEN in .env)
make test               # relay + app + ios + portal
make eval-conversion    # Part 4's conversion eval (when merged)
make deploy             # on the VM: relay + Caddy (+ portal) via docker compose
```

Mock relay quick check (PowerShell): `$env:MOCK_MODE='1'; $env:PORTAL_TOKEN='pt'; make dev-relay`,
then upload a markdown SOP to `POST /v1/materials` with `authorization: Bearer pt`.

## Actual results (2026-10-17)

- This branch: **relay 471 passed, 5 skipped**; app 202 passed; `test-ios` builds;
  portal skipped (not on this branch). Two deliberate sabotages (fast path off, approve gate
  off) turned 8 v2 tests red, then green again when restored.
- **Trial merge** of Parts 1, 4, 5 on top (not pushed): no conflicts; **relay 650 passed,
  9 skipped, 1 xfailed** (Part 4's strict xfail, see open requests); **app 418 passed**;
  **portal 8 passed**; **`test-ios` fails** on `Pills.tsx` lacking `command`.
- **Live conversion** on the integrated tree through `jobs.py`, Part 4's real `GeminiConverter`,
  `verify_step` and renderer, in-memory storage (no Tiger writes): SOP-153 markdown on
  `gemini-3.5-flash-lite` -> ready in 1.4 s, 4/4 steps verified with M5, 3 N-m, 0.10 mm kept,
  published, delivered as a 4-step walkthrough. `gemini-3.8-flash` returned 429 (free-tier daily
  cap); the job ended `failed` with "structuring failed: ClientError", never stuck.
- **Real renderer through the job + lens route:** Part 4's star-pattern spec -> two 288 x 144
  8-bit grey PNG tiles at lens levels (1,234 + 1,184 bytes), served byte-identical by
  `GET /v1/diagrams/{id}`.
- **Real Caddy 2.8.4** in front of the mock relay: `/portal` 308 -> `/portal/`, index, assets,
  SPA fallback, security headers, `/v1/*` proxied with auth intact, a 23 MB upload refused 413
  at the edge, a real multipart upload accepted 202.

## Not done / not proven

- v2 is **not deployed**; the VM still runs the v1 build on the sslip host. The domain switch
  (Caddy for `getyourassto.work`) is pending the owner's go-ahead.
- Nothing ran on glasses. No Sentry trace was captured (backburner).
- Postgres-backed v2 routes ran only through mocks and Part 5's own fixture tests; no live Tiger
  writes were made from this machine.

## Open requests

1. **Part 5:** `next_assignment` marks delivered before the lens has it; a lost response loses
   the task (suggest re-sending until the first progress event). Add `events.assignment_id` +
   the `write_event` parameter. Portal dev port 5176 collides with Part 1's v2 dev server.
2. **Companion owner / Parts 1-2:** add `command` to the `Record<Outcome, ...>` maps in
   `Pills.tsx` (`ios/` on this base, `app/src/phone/` on main) so `test-ios` passes.
3. **Part 4:** replace the strict xfail `("say that again", "command")` in `test_ask_trust.py`
   with "say that again" -> `repeat` (no task) and -> `command: repeat` (with `step_id`). Get a
   paid Gemini key for `gemini-3.8-flash` before the M3 demo.
4. **Part 1:** the final `app.json` origin is `https://getyourassto.work` once Caddy serves it.
5. **Part 2:** client v2 against the mock relay (pair -> poll `/me` -> Bearer on lens routes ->
   401 re-pair -> 204 no task -> batched progress).
