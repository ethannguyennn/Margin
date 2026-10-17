# Part 5 — Database, Corpus, Walkthrough/Deviation & Eval

**Branch:** `part-5-data-corpus`
**Owns:** everything Margin knows and everything it can prove. The Tiger Cloud
schema, the synthetic SOP corpus, ingestion, the walkthrough and deviation
features, and the eval harness that produces our quality numbers for the
pitch.

**Milestones:** M4 (data side) + M5 (walkthrough + deviation). Your corpus
blocks Part 4's retrieval and your eval harness is the slide that wins the
technical-depth argument — corpus first, eval second, everything else after.

---

## 1. Files you own

```
db/migrations/001_init.sql
db/seed.py                                    # parse -> chunk -> embed -> upsert
corpus/                                       # synthetic SOPs, markdown + front matter
relay/src/margin_relay/db.py                  # psycopg pool + every query
relay/src/margin_relay/notify/base.py         # Notifier protocol
relay/src/margin_relay/notify/console.py
relay/src/margin_relay/notify/photon.py
relay/src/margin_relay/walkthrough.py         # step assembly + deviation id allocation
eval/qa.jsonl
eval/run_eval.py
relay/tests/test_db.py, relay/tests/test_eval_harness.py
```

## 2. Files you must NOT touch

`main.py`, `config.py`, `schemas.py`, `routes/`, `obs.py`, `Makefile`,
`.env.example` (Part 3); `pipeline/{transcribe,intent,retrieve,generate,verify,sanitize}.py`
(Part 4); all of `app/` (Parts 1 and 2); and **`main`**.

Part 3 owns the routes. You own the functions the routes call. If you need a
new env var or a route change, post it in the channel.

## 3. Your dependency

Part 3 pushes `scaffold-relay` in the first hour (`config.py`, `schemas.py`,
the `Protocol`s). Then:

```bash
git fetch --tags && git merge scaffold-relay
```

Until then, **do not wait**: the corpus, the migration and `qa.jsonl` need
nothing from anyone. Write those first.

---

## 4. Schema (`db/migrations/001_init.sql`)

Vector dimension comes from `EMBED_DIM` (default 768) — keep the migration and
Part 4's embedding call reading the same config value, or every vector query
silently returns garbage.

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documents (
  doc_id         text,
  revision       text,
  title          text NOT NULL,
  status         text NOT NULL CHECK (status IN ('effective','superseded','draft')),
  effective_date date,
  PRIMARY KEY (doc_id, revision)
);

CREATE TABLE chunks (
  chunk_id   text PRIMARY KEY,               -- 'SOP-114:C:4.2'
  doc_id     text NOT NULL,
  revision   text NOT NULL,
  section    text NOT NULL,                  -- '4.2'
  is_step    boolean NOT NULL DEFAULT false,
  step_order int,
  heading    text,
  text       text NOT NULL,
  tsv        tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(heading,'') || ' ' || text)) STORED,
  embedding  vector(768),
  FOREIGN KEY (doc_id, revision) REFERENCES documents(doc_id, revision)
);
CREATE INDEX chunks_tsv_idx ON chunks USING gin (tsv);
CREATE INDEX chunks_vec_idx ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX chunks_doc_idx ON chunks (doc_id, revision, step_order);

CREATE TABLE sessions (
  session_id  uuid PRIMARY KEY,
  started_at  timestamptz NOT NULL DEFAULT now(),
  device      text,
  app_version text
);

CREATE TABLE events (
  ts          timestamptz NOT NULL DEFAULT now(),
  session_id  uuid,
  trace_id    text,
  intent      text,
  outcome     text,
  doc_ids     text[],
  transcript  text,
  latency_ms  jsonb
);
SELECT create_hypertable('events', 'ts', if_not_exists => TRUE);

CREATE TABLE deviations (
  deviation_id text PRIMARY KEY,             -- 'DEV-0007'
  ts           timestamptz NOT NULL DEFAULT now(),
  session_id   uuid,
  doc_id       text,
  step_id      text,
  text         text NOT NULL,
  notified     boolean NOT NULL DEFAULT false
);
```

`events` is a Timescale hypertable — that plus pgvector plus full-text in one
Postgres is the Tiger Data story, so make sure `make latency` actually reads
from it.

`chunk_id` format is `{doc_id}:{revision}:{section}` and Part 1 renders
`source` from its parts. Never change the separator without telling everyone.

## 5. `db.py`

Interface Part 3 and Part 4 call (nobody else opens a connection):

```python
async def init_pool() -> None: ...
async def ping() -> str: ...                       # 'ok' | 'down'  -> /v1/health
async def vector_top(q_embedding, k: int, revision: str | None) -> list[Chunk]: ...
async def fts_top(query: str, k: int, revision: str | None) -> list[Chunk]: ...
async def steps_for(doc_id: str, revision: str | None) -> list[Step]: ...
async def list_procedures() -> list[dict]: ...
async def write_event(session_id, trace_id, intent, outcome, doc_ids, transcript, latency_ms) -> None: ...
async def next_deviation_id() -> str: ...          # 'DEV-0007' from a sequence
async def insert_deviation(...) -> None: ...
```

- psycopg (async) connection pool, opened once at startup.
- `write_event` must **never** raise into the request path — a dead analytics
  write cannot cost us a demo answer. Log and swallow.
- `revision=None` means `status = 'effective'`. A passed revision forces it.

## 6. Corpus (`corpus/`) — synthetic only, build it first

Fictional product: **Halcyon HX-2 portable fluid pump**. Markdown with front
matter, numbered sections, tables, warnings and ordered step lists.

```markdown
---
doc_id: SOP-114
title: Mounting Bracket Assembly
revision: C
status: effective
effective_date: 2026-03-01
---
## 4 Procedure
### 4.1 Preparation ...
### 4.2 Fastening
Torque all four M5 bracket screws to 4 N-m in a star pattern using a calibrated torque wrench (see SOP-131).
```

Required documents:

| doc | title | notes |
|---|---|---|
| SOP-101 | Receiving inspection | |
| SOP-114 | Mounting bracket assembly | rev C **and** rev D; D changes the 4.2 torque value and adds one step. Mark C superseded / D effective **only in the fork demo** |
| SOP-120 | Cleaning and disinfection | include a degree symbol and a micro symbol so the sanitizer gets exercised |
| SOP-131 | Torque wrench calibration check | the cross-reference target |
| SOP-140 | Nonconformance and deviation reporting | |

Write real-sounding content with specific numbers and units. The demo question
is "How tight is the M5 on the mounting bracket?" and the trust moment is an
off-document question, so the corpus must be narrow and specific — a vague
corpus makes both the answer and the refusal unconvincing.

**Synthetic only. Never ingest any real employer or confidential SOP.**

## 7. Ingestion (`db/seed.py`, `make seed`)

- Parse front matter, split by section heading, chunk per section.
- Mark ordered procedural steps `is_step = true` with a `step_order`.
- `chunk_id = f"{doc_id}:{revision}:{section}"`.
- Embed with Part 4's embed helper (or Gemini directly through Part 3's
  config) at `EMBED_DIM`. Batch the calls.
- **Idempotent upsert** — you will re-run this twenty times.
- Also exposed as `POST /v1/ingest` behind `ADMIN_TOKEN` (Part 3's route calls
  your function).

## 8. Walkthrough + deviation (`walkthrough.py`) — M5

**Walkthrough.** Part 3's `/v1/ask` resolves the best-matching `doc_id` from
retrieval and asks you for the payload:

```json
{ "doc_id": "SOP-114", "revision": "C", "title": "...", "total": 7, "index": 0,
  "steps": [ { "step_id": "SOP-114:C:4.1", "label": "4.1", "glance": "...", "body": "..." } ] }
```

- **All steps at once.** The app navigates locally so swiping has zero
  latency; never make the lens wait on a network call to see step 4.
- `glance` <= 60 chars, `body` <= 450 chars, per step, sanitized.
- `label` is the human section number (`4.1`), not the chunk id.

**Deviation.** `next_deviation_id()` from a Postgres sequence, insert the row,
then call the Notifier and store whether it succeeded.

```python
class Notifier(Protocol):
    async def notify(self, deviation_id: str, text: str) -> bool: ...
```

- `ConsoleNotifier` — logs. **This is the default and it is enough for the
  demo.** `NOTIFIER=console` until Photon access is confirmed.
- `PhotonNotifier` — SMS/iMessage to `SUPERVISOR_ADDRESS` using
  `PHOTON_API_KEY`. Optional. A notifier failure must still return
  `notified: false` with a successfully stored deviation — **the record is the
  compliance artifact, the alert is a convenience.**

## 9. Eval harness (`eval/qa.jsonl` + `run_eval.py`) — our quality evidence

`qa.jsonl`, **25+ lines**:

```json
{ "q": "how tight is the m5 on the mounting bracket", "expect": "answered", "doc_id": "SOP-114", "section": "4.2", "must_contain": ["4 N-m"] }
```

Four categories, and the middle two are what make the number credible:

1. **answerable** — straightforward lookups across all five docs.
2. **near-miss** — plausible, similar-sounding, genuinely absent
   ("what is the torque on the M6 bracket screws", "cleaning interval for the
   HX-3"). These must come back `not_found`. This is where the thresholds get
   tuned.
3. **ambiguous** — could match two procedures; expect `not_found` with
   `needs_clarification`.
4. **unanswerable / off-domain** — "what's the wifi password".

`run_eval.py` runs each question through `/v1/ask` with the `text` field
(bypassing STT) and reports:

- answered-correct rate (right doc, right section, every `must_contain` present)
- `not_found` precision and recall
- citation-verification pass rate
- median latency

Print a compact table and a one-line summary we can paste into the Devpost
write-up. Exit non-zero if any **unverified** answer was returned — that is
the regression that must never ship.

## 10. Build order

1. `corpus/` — all five documents, real content. (Hour one; it blocks Part 4.)
2. `001_init.sql` applied to Tiger Cloud; confirm `vector`, `hnsw` and
   `create_hypertable` all work on our service tier before building on them.
3. `qa.jsonl` — write it while the corpus is fresh in your head.
4. `db.py` + `seed.py`, then `make seed`. Announce to Part 4 the moment
   retrieval has real rows to hit.
5. `walkthrough.py` + notifiers.
6. `run_eval.py`, then threshold tuning with Part 4.

## 11. Acceptance

- [ ] `make seed` is idempotent and reports chunk and step counts per doc.
- [ ] `/v1/procedures` lists all five docs; `/v1/procedures/SOP-114/steps`
      returns them in order.
- [ ] `make eval` runs end to end and prints the four metrics.
- [ ] Near-miss questions return `not_found`, not a confident wrong answer.
- [ ] A deviation survives a notifier failure: row stored,
      `notified: false`.
- [ ] `events` rows carry `latency_ms` so `make latency` (Part 3) has data.
- [ ] `write_event` failing does not fail the request (test it with a
      monkeypatched pool).
- [ ] `make test` green.

## 12. Stretch (only after M4/M5 are green)

Tiger **zero-copy fork**: fork the service, load SOP rev D there, set
`DATABASE_URL_FORK` (**verify the Tiger CLI fork syntax in their docs**).
Part 4 runs retrieval against both and appends `Changed in rev D` when the
cited step text differs. Behind a config flag; it must not be able to break
the main path.

## 13. Merge protocol (read once, it is short)

1. **Never commit to `main`.** `main` stays empty until the integration merge.
2. Commit and push to your own branch constantly. Small commits.
3. Pull `scaffold-relay` from Part 3 when announced.
4. Stay inside **Files you own**. If you need a change in someone else's file,
   post a one-line request in the channel; do not edit it.
5. Integration order into `main`: 1, 3, 2, 4, 5. You are last, so rebase onto
   the integration branch rather than waiting.
6. Do **not** add `Co-Authored-By: Claude` to commits.

## 14. House rules

- **Synthetic documents only.** No real employer or confidential SOPs, ever.
- Store transcript text and metrics. **Never store raw audio.**
- No API keys or credentials in `corpus/`, `qa.jsonl` or any committed file.
- `DATABASE_URL` comes from Part 3's config; never inline a connection string.
