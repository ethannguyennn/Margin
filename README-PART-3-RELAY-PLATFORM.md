# Part 3 v2 — Relay Platform, Contract & Deploy

**Branch:** `part-3-relay-platform`
**Read first:** `BUILD-PLAN-V2.md` (§5 contract and routes are yours to make real).
**Owns:** the FastAPI service, contract v2 server side, every route, the only
orchestrators (`/v1/ask` and the conversion job), device and portal auth,
uploads, config, Makefile, deploy. Parts 4 and 5 fill modules you define.

**Milestones:** M0 (`v2-scaffold-relay` tag), M2 (all v2 routes on mocks), M3
(real conversion + publish + assignment end to end), plus the still-open v1
bring-up (real Gemini, Tiger, domain, device CORS).

---

## 1. Files you own

```
Makefile, .env.example, relay/pyproject.toml
relay/src/specs_relay/main.py          # factory, CORS, routers, Sentry, pipeline + converter resolution
relay/src/specs_relay/config.py        # + PORTAL_TOKEN, DEVICE_TOKEN_SECRET, MAX_UPLOAD_MB, CONVERT_TIMEOUT_S, GEMINI_MODEL_CONVERT
relay/src/specs_relay/schemas.py       # contract v2 (BUILD-PLAN-V2 §5), SHARED
relay/src/specs_relay/auth.py          # portal bearer + device tokens (new)
relay/src/specs_relay/jobs.py          # conversion job runner (new)
relay/src/specs_relay/obs.py
relay/src/specs_relay/routes/          # ask.py (+command), devices.py, assignments.py, progress.py,
                                        # materials.py, drafts.py, diagrams.py (new); v1 routes kept
relay/src/specs_relay/pipeline/__init__.py   # + Converter, verify_step, DiagramRenderer, parse_command Protocols
relay/src/specs_relay/pipeline/mock.py       # + MockConverter, MockRenderer
relay/tests/test_routes*.py, test_auth.py, test_jobs.py, test_cors.py, test_boot.py
deploy/                                 # compose, Caddyfile (+ /portal static), healthcheck
TODO.md                                 # keep it current
```

## 2. Files you must NOT touch

`pipeline/{transcribe,intent,retrieve,generate,verify,sanitize}.py`,
`relay/src/specs_relay/convert/`, `relay/src/specs_relay/diagrams/`,
`eval/conversion/` (Part 4); `db.py`, `db/`, `notify/`, `walkthrough.py`,
`corpus/`, `eval/qa.jsonl`, `portal/` (Part 5); all of `app/`, `ios/`; and **`main`**.

---

## 3. Contract v2 first (hour one)

`schemas.py` gets every BUILD-PLAN-V2 §5 shape. Additive only: v1 models keep
their fields and caps. New caps: `warning <= 80`, `checkpoint <= 60`,
`DiagramSpec.alt <= 80`, `DiagramElement.label <= 12`, `elements <= 40`.
`AskResponse` validator: `outcome == 'command'` requires `command` and
`verified is False` and empty `glance/body/citations`. Add the Protocols and
mocks, keep `MOCK_MODE=1` booting with no DB, no key, no Part 4/5 modules.

```
git tag v2-scaffold-relay && git push origin part-3-relay-platform --tags
```

Announce it. Parts 4 and 5 are waiting.

## 4. `/v1/ask` v2 (still the one request flow)

Insert one step after transcription, before intent:

```
transcript -> parse_command(transcript)
   -> command? return {outcome: 'command', intent: 'command', command, verified: false, ...}
      immediately: no retrieval, no LLM, one events row.  (target: STT + 20 ms)
   -> else v1 flow, with context.assignment_id recorded on the events row
```

`repeat` inside a task (context has `step_id`) is a `command`, not v1's
replay of the last answer. Write the events row with `intent='command'` so
`make latency` can report command latency separately.

## 5. Auth (`auth.py`)

Ponytail scope, one organisation:

- **Portal:** `authorization: Bearer <PORTAL_TOKEN>` on every portal route,
  `hmac.compare_digest`, 401 otherwise. One shared token in `.env`. Real
  per-supervisor accounts / SSO are v3; say so in the README.
- **Device:** `POST /v1/devices/pair` is open (rate-limited: 10/min per IP)
  and mints `device_id` + a random 32-byte `device_token`; store only its
  SHA-256 (Part 5's table). `pair_code` = 4 chars from an unambiguous alphabet
  (no 0/O/1/I), unique among unclaimed devices, expires in 15 min. Every other
  lens route requires the token; it scopes `assignments/next` and `progress` to
  that device.
- Log rejected auth at WARN like rejected CORS origins. Never log tokens.

## 6. Conversion job (`jobs.py`)

`POST /v1/materials` stores the upload (Part 5's `insert_material`), returns
`{material_id, status: 'converting'}` immediately and starts the job in-process
(`asyncio.create_task`, tracked in a dict so shutdown can cancel it). Ponytail:
no queue service; one relay process, at most 2 concurrent conversions
(semaphore), and a job interrupted by a restart is marked `failed` on boot.

Job, timed and traced, each stage a Sentry span:

```
extract (Part 4) -> save MaterialText (Part 5)
-> convert (Part 4) -> for each step: verify_step (Part 4)
-> for each step with a diagram spec: render tiles + preview (Part 4) -> save diagram (Part 5)
-> save draft, status ready | failed (with a human-readable error)
```

Upload rules: `MAX_UPLOAD_MB` (default 20), allow-list of MIME types
(`application/pdf`, `.docx`, `text/markdown`, `text/plain`, `image/png`,
`image/jpeg`), check the magic bytes, not just the header. `doc_id`
`^[A-Z]{2,5}-\d{3}$`, `revision` `^[A-Z0-9]{1,3}$`, title <= 120.

Draft edits (`PUT .../steps/{label}`) re-run `verify_step` and caps on save
and return the result; the portal shows it inline. `POST .../approve`
returns 409 listing failing steps unless every step verifies and every
attached diagram is approved (or detached); then calls Part 5's
`publish_draft()` and returns the published steps.

## 7. Device, assignment, progress, diagram routes

Thin: validate, auth, call Part 5's `db.py`, map errors to the contract error
shape with a `trace_id`. `GET /v1/assignments/next` builds the `Walkthrough`
through Part 5's `build_walkthrough(doc_id, revision)` so a published
procedure, a seeded v1 SOP and a walk-me-through answer are one code path.
`GET /v1/diagrams/{id}` serves only approved diagrams of effective revisions
(404 otherwise); the lens never sees a draft.

## 8. Deploy & the v1 bring-up you still own

From `TODO.md` §1-2, still open: real Gemini key + models, Tiger
`DATABASE_URL`, `make seed` twice, real-mode `make health`, `make eval`,
threshold tuning (with Parts 4/5), `make deploy` on the VM,
`https://getyourassto.work/v1/health` from a phone on cellular, the device
CORS origin, `make latency`. Do these in week one alongside the scaffold;
v2 demos need a real relay.

New: Caddy serves Part 5's `portal/dist` at `/portal/` from the same origin
as the API (no CORS for the portal). Upload size limit set in Caddy too.
`app/app.json` whitelist moves from `https://45-32-88-132.sslip.io` to
`https://getyourassto.work` once DNS answers; give Part 1 the exact string.

New env vars: `PORTAL_TOKEN`, `DEVICE_TOKEN_SECRET` (if you sign anything),
`MAX_UPLOAD_MB=20`, `CONVERT_TIMEOUT_S=180`, `GEMINI_MODEL_CONVERT=` (Part 4
picks; look up the current model ID, do not guess).

## 9. Build order

1. `schemas.py` v2, Protocols, mocks, tag `v2-scaffold-relay`. (Hour one.)
2. Command fast path in `/v1/ask` + tests. Tell Part 2.
3. `auth.py`, device / assignment / progress / diagram routes on mocks.
4. Materials + drafts routes + `jobs.py` with `MockConverter`; the portal
   (Part 5) and conversion (Part 4) both develop against this.
5. Real-mode factory wiring for Parts 4/5 modules as they land.
6. v1 bring-up + deploy + portal static serving.

## 10. Acceptance

- [ ] `MOCK_MODE=1` boots with no DB, no key, no Part 4/5 v2 modules; every
      BUILD-PLAN-V2 §5 route answers with a schema-valid mock.
- [ ] A command utterance never touches retrieval or the LLM (call counters),
      and its relay time is STT + < 50 ms.
- [ ] Portal routes 401 without the token; lens routes 401 without a device
      token; a device cannot read another device's assignment or progress.
- [ ] Approve is refused (409) with any unverified step or unapproved attached diagram.
- [ ] A relay restart during a conversion leaves the material `failed`, not stuck in `converting`.
- [ ] Oversized and wrong-type uploads are rejected before they are stored.
- [ ] `https://getyourassto.work/v1/health` and `/portal/` from a phone on cellular.
- [ ] One unbroken Sentry trace: lens gesture -> capture -> upload -> stt -> command/answer -> render.
- [ ] `make test` green (relay, app, ios).

## 11. House rules

Every v1 rule (BUILD-PLAN-V2 §8). All keys and tokens live in `.env` only; the
app bundle and the portal bundle contain none. Uploaded files are stored, so
the synthetic-only rule is now enforced by people, not code: say so in the
portal UI. Do **not** add `Co-Authored-By: Claude` to commits.
