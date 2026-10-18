# Part 5 v2 handoff

Date: 2026-10-17 (America/Los_Angeles).
Branch: `part-5-portal-data`.
Final tested implementation commit: `b216976fe4b9b795222db670e754ccac7238d0d3`.
Data commit: `b882b659fc1220e40bc354fcb9f1dab1d9d238ae`.
The handoff follow-up only documents results, cleans trailing blank lines and
makes the browser test's installed-tool path relative to USERPROFILE.

Owned implementation and independent fixture validation are complete. M3 and
live Tiger acceptance remain pending. The user explicitly asked to wait for
Part 3 dependencies until a later team merge. No live database or credential
probe was attempted after that instruction. No real-system result is claimed.

## Delivered

- Additive migration 002: materials, drafts, diagrams, hashed device tokens,
  pinned assignments, progress hypertable and step extras. Its unique index
  includes the partition timestamp and coalesces NULL step IDs, so retries of
  task-level events deduplicate too. Actual Timescale acceptance remains a live
  gate, not something proven by query-recording unit tests.
- Upload/diagram bytea columns are capped at 20 MB; the required ponytail
  comment names object storage as the upgrade path. The extra nullable
  `chunks.body` column preserves the reviewed lens body while `chunks.text`
  remains the verbatim source quotes used by v1 retrieval and answer checking.
- Every production SQL query/connection stays in db.py. Existing v1 query
  signatures remain usable. Revision None still filters effective documents.
- publish_draft reloads the durable draft, calls Part 4's verifier against the
  stored material, checks warning grounding and diagram approval, and reuses
  the existing batched embedding helper. Provider work finishes before the
  transaction. The transaction locks the document/draft/source, rejects
  concurrent edits, rechecks diagram approval, supersedes the previous effective
  revision, inserts chunks/embeddings and marks approval together. No assignment
  revision is rewritten. Published revisions are immutable, including v1
  revisions; re-approving an old draft does not reactivate it. Re-seeding v1
  markdown cannot displace a portal-published revision.
- steps_for/build_walkthrough return authored body, warning, checkpoint and
  approved diagram metadata through the shared Step model after the v2 schema
  arrives. The current v1 schema cannot serialize those new fields yet.
- Progress uses ON CONFLICT DO NOTHING, authenticates the device scope in its
  INSERT SELECT, and returns 0 on failure/timeout without leaking an exception
  into the request path. The board retains the last non-null step while paused,
  tracks step start time, and includes procedure-level v1 deviations. Completed
  assignments leave the active board.
- latency_summary excludes missing/skipped stages represented by zero. The
  lexical leg now uses the same OR expansion already in Part 4's PgStore.
- Portal: same-origin token login, sessionStorage, multipart upload/status
  polling, source highlighting, editable fields/counts, PASS/FAIL reasons,
  shared renderScreen preview, authenticated PNG previews, diagram approval/
  detachment, guarded publication with 409 reasons, devices, assignment and
  3-second board polling. Inputs are labeled, focus is visible, and all
  uploaded/API text is rendered as text rather than injected HTML.

No Makefile, deployment, schemas, routes, pyproject, conversion, app or ios
source was edited. Only this branch was pushed. The primary checkout's local
changes were preserved; work took place in `.part5-worktree`.

## Exact commands

Run from this checkout's repository root. On Windows use the following; on
POSIX substitute `.venv/bin/python` and standard environment assignment syntax.
No command contains a credential. DATABASE_URL and provider settings must come
from Part 3's config/.env after the team merge.

```powershell
# Install the repository's existing relay dependencies if needed:
python -m venv .venv
& .venv/Scripts/python.exe -m pip install -e 'relay[dev]'

# Local parser check: no DB or provider needed.
& .venv/Scripts/python.exe db/seed.py --check

# AFTER database access is supplied: capability/migration validation.
& .venv/Scripts/python.exe db/seed.py --probe-only
& .venv/Scripts/python.exe db/seed.py --probe-v2-only
# The v2 probe applies 001 + 002 twice to synthetic v1 rows in an isolated
# schema, tests NULL and non-NULL progress retries, reports its index, then
# rolls back. Its counts are explicitly synthetic, not production counts.

# Apply to the actual application schema twice; each call prints before/after
# counts for every owned table without printing a DSN or upload content.
& .venv/Scripts/python.exe db/seed.py --migrate-only
& .venv/Scripts/python.exe db/seed.py --migrate-only

# Seed v1 markdown, then optionally restore approved v2 authoring data.
& .venv/Scripts/python.exe db/seed.py
& .venv/Scripts/python.exe db/seed.py --from-drafts
# --from-drafts reads approved rows already restored/cloned into this DB.
# Materials (including text), drafts and diagrams must be restored together;
# it does not export data or import arbitrary JSON files.

npm --prefix portal ci
npm --prefix portal run dev          # :5178/portal/, API proxy -> :8080
npm --prefix portal run build        # portal/dist, production /portal/ base
npm --prefix portal test

# Independent, clearly labeled fixture API. Not Part 3's mock relay.
npm --prefix portal run dev:fixture  # :5177/portal/, token: fixture-token
# In a second shell:
& portal/tests/browser-smoke.ps1

# Required regression equivalents (make is unavailable on this host):
& .venv/Scripts/python.exe -m pytest relay/tests -q
npm --prefix app ci
npm --prefix app test
npm --prefix ios ci
npm --prefix ios run build

# Opt in to the live rollback-only probe once access is ready:
$env:SPECS_TEST_V2_DATABASE = '1'
& .venv/Scripts/python.exe -m pytest relay/tests/test_db_v2_live.py -q
Remove-Item Env:SPECS_TEST_V2_DATABASE
```

When GNU make is available, run `make test` and `make test-ios`. Part 3 still
needs to add the portal build/test targets and include them in CI.

The existing v1 mock evaluation was run with:

```powershell
$env:MOCK_MODE = '1'
& .venv/Scripts/python.exe -m uvicorn specs_relay.main:create_app --factory --host 127.0.0.1 --port 8086
# In a second shell:
& .venv/Scripts/python.exe eval/run_eval.py --base-url http://127.0.0.1:8086 --allow-mock --output portal/tests/v1-mock-eval.json
```

For the baseline, the same interpreter ran uvicorn on :8087 with PYTHONPATH
pointing to the untouched a5cffda checkout's relay/src. Its output is
`portal/tests/v1-base-mock-eval.json`. Comparing all 36 per-case outcomes,
verification flags and reasons after removing latency gives identical results.

## Actual test and migration evidence

| Check | Result |
| --- | --- |
| Complete relay suite | 377 passed, 11 skipped, 1 existing Starlette deprecation warning |
| Portal jsdom tests | 8 passed, including upload-to-board fixture flow |
| Portal tsc + Vite production build | Passed; JS about 19 KB / 7.62 KB gzip |
| App tests | 202 passed, 6 skipped |
| Frozen ios TypeScript + Vite build | Passed |
| Local corpus parser | 59 chunks / 35 steps, unchanged |
| make test | Could not launch: make is not installed/on PATH; its three constituent checks passed directly |
| V1 mock eval | Exit 1, 24 existing quality failures; identical to base, zero unverified answers |
| Tiger migration twice, real row counts | NOT RUN: waiting for team merge/access |
| Tiger progress unique-index verification | NOT RUN; opt-in rollback probe committed |
| Part 3 v2 mock relay flow | NOT RUN: v2-scaffold-relay and routes not published |
| Part 4 real conversion + real relay flow | NOT RUN: modules/materials and integrated relay pending |

New skipped gates cover the missing shared v2 models, walkthrough extras and
live Tiger probe. Existing provider/database integration skips remain unchanged.
`portal/tests/evidence/relay-tests.txt` and `portal-tests.txt` record the runs.

Publication tests prove snapshot/rollback behavior with a query recorder, quote
preservation, diagram rechecks, failed-verifier rejection, concurrent-edit
rejection, revision protection and approved-draft restore selection. The
actual v1 /v1/ask HTTP handler and real deterministic answer verifier also
accepted the published quote chunks with a verbatim citation in an ASGI test;
its database/provider/publication commit are fixtures. This is not evidence of
SQL execution or real retrieval against Tiger. The shared-v2 walkthrough
serialization assertion remains skipped until the contract merge.

The two v1 mock evaluations both report 18.8% answered-correct, 57.1% not_found
precision, 60.0% recall, 100% citation verification and zero unverified answers.
Those are mock behavior, not product quality measurements or a green eval gate.

## Browser, usability and latency evidence

`portal/tests/evidence/browser-fixture.txt` records a successful gstack /browse
run through synthetic text upload, failing step, correction, diagram approval,
publication, pairing, assignment and board updates. It reports no console
errors and confirms the synthetic banner and inline deviation. Screenshots:
`review-fixture.png`, `board-fixture.png`, `board-mobile-fixture.png`.

The last browser fixture run measured **3448 ms** from updating fixture state
to the board showing step 2/6. This includes browser/test-command overhead but
excludes the lens's 5-second flush, real HTTP progress ingestion and database
latency. It does not establish the required <= 8-second real lens-to-board gate.
An earlier fixture run measured 3419 ms. Browser persistence was unreliable
between tool calls on this host; the reproducible script runs the whole flow
in one browse chain and treats errors/timeouts as failures.

**Teammate usability test: NOT RUN.** No unfamiliar human participant or Part 4
SOP-150-pump-seal-swap.pdf was available. No under-five-minute time is claimed.
After integration, time the specified PDF flow with a new participant, including
one failed-step correction, diagram approval, pairing and assignment. Record
elapsed time and observations here. The automated text fixture is not that test.

## Integration requests after the team merge

Part 3:

1. Publish/merge v2-scaffold-relay, the shared v2 models and every authenticated
   route/mock. No substitute production schemas/routes were added by Part 5.
2. Add portal build/test Makefile targets, CI and Caddy serving portal/dist at
   /portal/ on the API origin. Part 5 requires no new Python dependency/env var.
3. Initialize the existing db pool, apply both migrations, and call
   fail_interrupted_materials() on boot for interrupted conversions.
4. POST materials calls insert_material(filename, mime, data, doc_id, revision,
   title). Jobs can use get_material(id, include_bytes=True); normal reads omit
   bytes. Save MaterialText, diagrams and the shared ProcedureDraft, then set
   the material status to ready/failed. get_material_text(id) is provided.
5. PUT step edits must reverify with Part 4, call update_draft_step and refetch
   the stored step so invalidated diagram approval is reflected. Human approval
   is never accepted from converter-supplied diagram_approved flags.
6. Approve calls walkthrough.publish_draft(doc_id, revision) or passes the shared
   ProcedureDraft. LookupError means missing, ValueError contains readable
   reasons suitable for 409. Return its doc_id/revision/step count.
7. insert_progress(events, device_id=authenticated_device_id) is mandatory for
   device scope. Omitting the authenticated ID fails closed with accepted=0.
   Timestamps are Unix milliseconds. Route auth and ownership checks remain
   Part 3's responsibility. Pairing rows expose claimed_at; map it to claimed
   and never return token_sha256 or a new device's token in the portal list.
8. Current ask.py reconstructs Step using only its four v1 fields: forward
   warning/checkpoint/diagram when merging. Its walkthrough citation currently
   quotes s.body; authored v2 bodies may paraphrase, so resolve citations from
   the stored chunk's source quotes rather than labeling a paraphrase verbatim.
9. Approved diagrams are returned for effective revisions or revisions still
   pinned to active assignments. Keep the route's authorization compatible with
   that rule so an in-flight task does not lose its diagram after publication
   of a new revision. No unapproved diagram passes get_diagram's default filter.
10. Supply DATABASE_URL and PORTAL_TOKEN through .env when ready, never in chat
    or committed files. Run the real-relay acceptance flow and real v1 eval.

Part 4: merge the real convert.verify_step.verify_step implementation, converter,
renderer and four synthetic demo materials. Confirm the 576x144 preview PNG and
1-2 288x144 lens tiles. The portal fixture artwork is not renderer evidence.

Part 1: keep the stable renderScreen export. The current shared renderer is v1;
the portal imports it directly and will use the merged implementation.

## Database identifiers and remaining limits

No Tiger service ID, database hostname or branch identifier has been supplied
for this task; none is invented. Runtime settings are exclusively Part 3's
DATABASE_URL/EMBED_DIM and existing embedding config. IDs in fixture evidence
(MAT-1, DGM-1, LNS-1, ASN-1, SOP-150/A) are synthetic local fixture identifiers,
not cloud records. The live probe uses a unique specs_v2_probe_* schema and
rolls it back.

This is one organisation with one shared portal token. V1 deviations contain
procedure/step, not assignment/device identity; the board labels them procedure
deviations and may show one deviation on multiple active assignments to that
procedure. No accounts, roles, analytics, exports or deployment work was added.
Live migration, full relay integration, actual PDF conversion, teammate timing,
real lens latency and device rendering remain explicit acceptance gates.
