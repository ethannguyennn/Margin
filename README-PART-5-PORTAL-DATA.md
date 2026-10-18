# Part 5 v2 — Employer Portal, Data & Publishing

**Branch:** `part-5-portal-data`
**Read first:** `BUILD-PLAN-V2.md` (§2 flow, §5 routes and shapes).
**Owns:** everything Margin stores and the only screen the employer ever sees:
migration 002, `db.py` v2, publishing an approved draft into the corpus the
lens and Q&A already use, and the web portal (upload, review, approve, pair,
assign, live progress).

**Milestones:** M2 (schema + `db.py` v2 behind Part 3's routes), M3 (portal
end to end against the real relay), M5 (progress board + pitch numbers).

---

## 1. Files you own

```
db/migrations/002_v2.sql
db/seed.py                                # + accepts published drafts; v1 corpus still seeds
relay/src/margin_relay/db.py              # + every v2 query
relay/src/margin_relay/walkthrough.py     # + step extras (warning, checkpoint, diagram), publish_draft()
relay/src/margin_relay/notify/
corpus/*.md, eval/qa.jsonl, eval/run_eval.py  # v1, maintenance
portal/                                   # NEW: Vite + vanilla TypeScript, no framework
relay/tests/test_db*.py, test_publish.py
portal/tests/
```

The iPhone companion (`ios/`) is frozen for v2: no new work, but keep `make
test-ios` green when the contract changes (it re-exports `app/src/types.ts`).

## 2. Files you must NOT touch

`main.py`, `config.py`, `schemas.py`, `routes/`, `jobs.py`, `auth.py`,
`pipeline/__init__.py`, `pipeline/mock.py`, `Makefile`, `deploy/` (Part 3);
`pipeline/{transcribe,intent,retrieve,generate,verify,sanitize}.py`,
`convert/`, `diagrams/`, `corpus/materials/`, `eval/conversion/` (Part 4);
all of `app/`; and **`main`**.

Depend on `v2-scaffold-relay` (`git fetch --tags && git merge v2-scaffold-relay`).

---

## 2a. Why the portal is vanilla

The portal is six forms and two tables for one supervisor. Vite is already the
team's tool (`app/`, `ios/`); TypeScript without a framework, `fetch`, native
`<input type="file">`, `<dialog>`, `<table>`. No component library, no state
library, no router beyond `location.hash`. If it outgrows that, v3 can decide.

## 3. Schema (`db/migrations/002_v2.sql`)

Additive. v1 tables unchanged except new nullable columns on `chunks`.

```sql
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS glance text;       -- explicit step glance (v1 derived it from heading)
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS warning text;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS checkpoint text;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS diagram_id text;

CREATE TABLE IF NOT EXISTS materials (
  material_id text PRIMARY KEY,            -- 'MAT-0001'
  created_at  timestamptz NOT NULL DEFAULT now(),
  filename    text NOT NULL,
  mime        text NOT NULL,
  bytes       bytea NOT NULL,              -- ponytail: <= 20 MB, Postgres not a bucket; object storage when files grow
  sha256      text NOT NULL,
  doc_id      text NOT NULL, revision text NOT NULL, title text NOT NULL,
  status      text NOT NULL CHECK (status IN ('converting','ready','failed','approved')),
  error       text,
  material_text jsonb                      -- MaterialText
);
CREATE TABLE IF NOT EXISTS drafts (
  doc_id text, revision text, material_id text NOT NULL REFERENCES materials,
  title text NOT NULL, steps jsonb NOT NULL, warnings jsonb NOT NULL DEFAULT '[]',
  updated_at timestamptz NOT NULL DEFAULT now(), approved_at timestamptz,
  PRIMARY KEY (doc_id, revision)
);
CREATE TABLE IF NOT EXISTS diagrams (
  diagram_id text PRIMARY KEY,             -- 'DGM-0001'
  doc_id text NOT NULL, revision text NOT NULL, step_label text NOT NULL,
  spec jsonb NOT NULL, tiles bytea[] NOT NULL, preview_png bytea NOT NULL,
  approved boolean NOT NULL DEFAULT false
);
CREATE TABLE IF NOT EXISTS devices (
  device_id text PRIMARY KEY, token_sha256 text NOT NULL UNIQUE,
  pair_code text, pair_expires timestamptz, worker_name text, claimed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS devices_open_code ON devices (pair_code) WHERE claimed_at IS NULL;
CREATE TABLE IF NOT EXISTS assignments (
  assignment_id text PRIMARY KEY,          -- 'ASN-0001'
  device_id text NOT NULL REFERENCES devices, doc_id text NOT NULL, revision text NOT NULL,
  assigned_at timestamptz NOT NULL DEFAULT now(), delivered_at timestamptz, completed_at timestamptz
);
CREATE TABLE IF NOT EXISTS progress (
  ts timestamptz NOT NULL, assignment_id text NOT NULL, step_id text, kind text NOT NULL,
  received_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (assignment_id, step_id, kind, ts)  -- idempotent batches; VERIFY a unique constraint is allowed on a hypertable incl. ts
);
SELECT create_hypertable('progress', 'ts', if_not_exists => TRUE);
```

Sequences for `MAT-`, `DGM-`, `ASN-` ids, as v1 did for `DEV-`.

## 4. `db.py` v2

Every query lives here (nobody else opens a connection), same pool, same
"analytics writes never raise into the request path" rule for `progress`.

```python
async def insert_material(...) -> str
async def set_material_status(material_id, status, error=None) -> None
async def save_material_text(material_id, text: MaterialText) -> None
async def get_material(material_id) -> dict | None           # without bytes unless asked
async def save_draft(draft: ProcedureDraft) -> None
async def get_draft(doc_id, revision) -> ProcedureDraft | None
async def update_draft_step(doc_id, revision, label, step: DraftStep) -> None
async def save_diagram(doc_id, revision, label, spec, tiles, preview) -> str
async def approve_diagram(diagram_id) -> None
async def get_diagram(diagram_id, approved_only=True) -> dict | None
async def create_device(token_sha256, pair_code, expires) -> str
async def claim_device(pair_code, worker_name) -> dict | None
async def device_by_token(token_sha256) -> dict | None
async def list_devices() -> list[dict]
async def create_assignment(device_id, doc_id, revision) -> str
async def next_assignment(device_id) -> dict | None           # oldest undelivered, marks delivered
async def insert_progress(events) -> int                      # ON CONFLICT DO NOTHING
async def progress_board(since) -> list[dict]
```

## 5. Publishing (`walkthrough.publish_draft`)

Approve is where a draft becomes something the lens and Q&A can use, through
the **same tables v1 already reads**, so retrieval, walkthroughs and the
verifier need no changes:

1. In one transaction: insert `documents (doc_id, revision, title,
   status='effective', effective_date=today)`, mark the previous effective
   revision `superseded`.
2. One chunk per step: `chunk_id = doc_id:revision:label`, `is_step = true`,
   `step_order`, `heading = glance`, `text` = the step's quotes joined (the
   verbatim material, so v1's answer verifier quotes the employer's own words),
   plus `glance`, `warning`, `checkpoint`, `diagram_id` (approved only).
3. One non-step chunk per document-level warning.
4. Embed with the existing batch embed helper; commit; mark the draft approved.
5. `build_walkthrough` / `steps_for` return the new columns, so
   `/v1/assignments/next` and "walk me through" both carry warning, checkpoint
   and diagram.

`db/seed.py` keeps seeding v1 markdown; `--from-drafts` re-publishes approved
drafts (for a fresh database). Idempotent, as v1.

## 6. Portal (`portal/`)

Served by Part 3's Caddy at `https://getyourassto.work/portal/`, same origin as
the API. Token entered once on a login screen, kept in `sessionStorage`, sent
as `authorization: Bearer`. Banner on every page: **"Demo build: upload
synthetic material only."**

| Screen | Does |
|---|---|
| **Upload** | file + doc_id + title + revision -> `POST /v1/materials`; status polled every 2 s until ready/failed |
| **Review** (the important one) | three columns per step: source quote(s) highlighted in the material text \| editable glance / body / warning / checkpoint with live char counts \| a 576x288 lens preview using the app's own `renderScreen` from `app/src/ui/screens.ts` (import it, do not re-implement it). Verify result inline per step, red with the reason when failing. Save -> `PUT`, re-verified |
| **Diagrams** | per step: the lens-exact preview PNG, approve / detach |
| **Approve** | disabled until every step passes and every attached diagram is approved; shows the 409 reasons if the relay refuses |
| **Devices** | enter the pair code shown on the lens + worker name -> claim; list devices |
| **Assign** | pick device + effective procedure -> assign |
| **Board** | one row per active assignment: worker, procedure, step n/total, minutes on current step, last event; polls `/v1/progress` every 3 s; deviations from v1 `deviations` shown inline |

Accessibility basics: labels on every input, keyboard reachable, visible
focus, no colour-only status (verify badges say PASS / FAIL in text).

## 7. Build order

1. `002_v2.sql` applied to Tiger; confirm the hypertable unique constraint.
2. `db.py` v2 + tests against a real Tiger branch / local Postgres. Tell Part 3.
3. `publish_draft` + test: publish a hand-written draft, then `steps_for` and
   `/v1/ask` "walk me through" return it with extras; v1 `make eval` unchanged.
4. Portal skeleton against Part 3's mock relay: Upload, Review, Approve.
5. Devices, Assign, Board.
6. Real relay + Part 4's real conversion of `corpus/materials/` end to end (M3).
7. v1 maintenance from `TODO.md` §4 (`latency_summary` 0 ms rows; lexical leg with Part 4).

## 8. Acceptance

- [ ] `002_v2.sql` is idempotent and applies on top of v1 data without loss.
- [ ] **M3 by hand, timed:** a teammate who has not seen the portal uploads
      `SOP-150-pump-seal-swap.pdf`, fixes one failing step, approves the
      diagram, approves, pairs the simulator and assigns the task in **under 5
      minutes**. Record the time.
- [ ] A published procedure is answerable through v1 `/v1/ask` with citations
      to the employer's text, and walks through with warnings / checkpoints / diagrams.
- [ ] Re-publishing a new revision supersedes the old one; in-flight
      assignments keep their pinned revision.
- [ ] Duplicate progress batches create no duplicate rows.
- [ ] The board reflects a lens "next" within 8 s (5 s client flush + 3 s poll).
- [ ] `make test` green including `make test-ios`.

## 9. House rules

Every v1 rule (BUILD-PLAN-V2 §8). Synthetic material only, enforced by the
banner and by us. Never inline a connection string; `DATABASE_URL` comes from
Part 3's config. The portal bundle holds no secrets; the token is typed in. Do
**not** add `Co-Authored-By: Claude` to commits.
