# Part 5 integration handoff

All corpus content is fictional, synthetic HX-2 training data. No employer SOPs,
credentials, or raw audio are included.

## Current evidence (2026-10-17)

- 76 Python tests pass against the merged scaffold-relay shared config/models.
  These exercise parser/embedding fixtures, query
  construction and transaction boundaries, walkthrough assembly, notifier failure,
  and HTTP-client evaluation scoring. They are **not** Tiger Cloud or Gemini evidence.
- The original 71-test suite also passed with Part 4's published sanitizer at 5425a67.
  Its real fuse/step-mapping functions accept the Part 5 store adapter's fixture
  rows. This is an interface check, not a live database or retrieval-quality test.
- Local parser counts: **59 chunks, 35 steps**, six revision files, five procedures.
  Effective corpus: **47 chunks, 27 steps**, five effective revisions.
- **No rows have been seeded into Tiger Cloud.** DATABASE_URL and Gemini credentials
  are intentionally deferred by the user.
- The rollback-only vector/HNSW/hypertable probe is implemented but has not run on
  Tiger Cloud. Docker Desktop also did not provide a working local engine.
- scaffold-relay (0d90a62) is merged. Real Part 3 HTTP handlers were tested through
  ASGI with fixture DB rows and embedding responses: procedure listing, ordered
  steps, complete walkthrough, latency event writing, notifier failure, authorized
  ingestion, and the evaluator against the real mock relay. This is not cloud evidence.
- A deployed real-mode relay, the Makefile, and cloud credentials remain unavailable.
  Runtime shared models are imported from Part 3. The test-only sanitizer stand-in
  remains necessary until Part 4's implementation is merged.
- Live quality metrics, near-miss tuning, HTTP procedure/deviation routes, make seed,
  make eval, make latency, and the full-project make test remain integration checks.
  No product quality percentages are claimed from answer-key fixtures.

| Document | Revision | Default status | Chunks | Steps |
| --- | --- | --- | ---: | ---: |
| SOP-101 | A | effective | 9 | 5 |
| SOP-114 | C | effective | 11 | 7 |
| SOP-114 | D | draft | 12 | 8 |
| SOP-120 | B | effective | 9 | 5 |
| SOP-131 | A | effective | 9 | 5 |
| SOP-140 | A | effective | 9 | 5 |

Revision C specifies 4 N-m in 4.2; D specifies 5 N-m and adds 4.8 independent
signoff. No default path promotes D or supersedes C. Fork support and Photon
delivery are intentionally deferred until the primary integration passes.

## Reproduce without secrets

Run from the repository root:

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/Scripts/python.exe -e "relay[dev]"
.venv/Scripts/python.exe db/seed.py --check
.venv/Scripts/python.exe -m pytest relay/tests -q
```

On POSIX use .venv/bin/python in place of .venv/Scripts/python.exe.
Part 3 owns relay/pyproject.toml.

## Part 3 wiring

No production environment variables were added. Settings are read exclusively
from specs_relay.config.get_settings(); lower-case setting attributes and their
upper-case environment-style equivalents are accepted:

- DATABASE_URL, EMBED_DIM
- GEMINI_API_KEY, GEMINI_MODEL_EMBED
- NOTIFIER, with console as Part 3's default

Startup/shutdown: await db.init_pool(), await db.close_pool().
db.ping() returns ok/down. The scaffold includes psycopg and google-genai.
Part 3 must promote PyYAML from dev-only to runtime dependencies for deployed
ingestion, and include corpus/ and db/ in the runtime image. The actual ingest
route now works through db.ingest_corpus(path), which resolves db/seed.py from
the checkout even when the server has another working directory.

| Route/tool owned by Part 3 | Part 5 call |
| --- | --- |
| GET /v1/procedures | await db.list_procedures() |
| GET /v1/procedures/{doc_id}/steps | await db.steps_for(doc_id, revision) |
| Walkthrough branch of /v1/ask | await walkthrough.build_walkthrough(doc_id, revision) |
| POST /v1/deviation / deviation branch of ask | await walkthrough.log_deviation(session_id, text, doc_id, step_id) |
| Authenticated POST /v1/ingest | await db.ingest_corpus(corpus_path) after pool initialization/migration |
| One analytics write per request | await db.write_event(session_id, trace_id, intent, outcome, doc_ids, transcript, latency_ms) |
| make latency | await db.latency_summary() after pool initialization |

Return walkthrough dictionaries directly; they include every step and index=0.
Map missing documents/steps (LookupError) to the route's not-found behavior.
Map invalid context/text (ValueError) to bad_request. No procedural body is
silently truncated: a body of 450 or more sanitized characters fails validation.

Chunk construction matches the actual shared model: chunk_id, doc_id, revision,
section, heading, title, text, is_step, step_order, and sim for cosine similarity.
The raw retrieval adapter preserves score for fusion. Step construction uses
step_id, label, glance, body. These are not redefined in production.

**Factory wiring request:** main._PoolStore currently treats db.pool (a callable
accessor) as a pool object, then constructs PgStore with that function. This will
fail on .connection(). Use Retriever(db.RetrievalStore(), embedder) so both the
raw-row contract and sole SQL ownership are respected.

**Deviation route request:** routes/deviation.py currently notifies before
inserting. Delegate to walkthrough.log_deviation(..., notifier=p.notifier), which
commits the false-status record first, then notifies and updates status. The
route's failure-response behavior is tested, but its ordering still needs this
Part 3 change. Its console success message also must not imply human receipt.

**Response-contract request:** ambiguous eval cases require outcome=not_found
and needs_clarification=true. The actual AskResponse model forbids that field and
the ask route discards Draft's flag. Please add it to the shared response model
and propagate the flag; the harness deliberately fails ambiguous cases without it.

Makefile commands remain owned by Part 3 and are not in this scaffold: seed -> python db/seed.py,
eval -> python eval/run_eval.py, latency -> db.latency_summary. No Makefile,
config, schemas, routes, pipeline module, or app file was edited by Part 5;
scaffold files arrived only through the authorized tag merge.

## Part 4 wiring

The published Retriever at 5425a67 accepts a Store. Use:

```python
from specs_relay import db
from specs_relay.pipeline.retrieve import Retriever

retriever = Retriever(db.RetrievalStore(), embedder)
```

This keeps all connections and production SQL in db.py. The adapter returns
raw chunk dictionaries (including score, text and section); the public
db.steps_for returns shared Step models. Do not pass those Step models through
step_from_row a second time. Do not use Retriever.from_pool/PgStore, which would
create another SQL owner. The direct vector_top/fts_top APIs return shared Chunk
models as required by the written interface.

The DB lexical query follows the frozen websearch_to_tsquery contract. The
published PgStore has a different OR-expansion query; coordinate any lexical
change here and tune both retrieval thresholds using the ten near-misses.

Seed and query must use the same configured model and dimension. Seed batches
32 separate Content objects per request and normalizes each embedding. Google's
[embedding documentation](https://ai.google.dev/gemini-api/docs/embeddings)
distinguishes task_type for Embedding 001 from prompt instructions for Embedding 2.
For Embedding 2, lists of bare strings may aggregate; the published Part 4
embed_documents helper needs separate Content objects before being used for
multi-document ingestion. Our direct SDK path already uses those objects.

## Once credentials and scaffold are available

```sh
git fetch origin --tags
# scaffold-relay is already merged here; pull subsequent Part 3 integration changes.
# Rebase on the team's integration branch when it has been published.
python db/seed.py --probe-only
python db/seed.py
python db/seed.py
python eval/run_eval.py --base-url http://127.0.0.1:8000 --output eval/live-results.json
```

The probe creates a uniquely named schema, exercises vector/HNSW/Timescale,
checks the hypertable catalog, and rolls back everything. It prints extension
versions only after success. It proves capability on the configured endpoint,
not the endpoint's commercial service tier; identify the actual Tiger service
in the integration evidence.

The seed command probes first, renders 001_init.sql with config's EMBED_DIM,
applies it transactionally, embeds the corpus, then atomically upserts documents
and chunks. An existing vector dimension mismatch requires an explicit migration;
it is not silently resized. IDs remain doc_id:revision:section. Repeated seeds
must return the table's same 59/35 counts. Removed sections are deleted only from
revisions supplied in that ingest; unrelated documents are preserved.

Use a dedicated test service for destructive/failure injection. Confirm:

1. The second seed has identical IDs/counts and no duplicate rows.
2. The real procedure list has five effective documents; SOP-114/C has seven
   ordered steps. Explicit D has eight without changing default status.
3. A notifier that raises leaves its deviation row stored with notified=false.
   The insert commits before notification. A failed notification-status update
   returns false conservatively and leaves the saved row intact.
4. A text ask writes an events row containing stage timings and total. The
   latency summary reads that hypertable, with p50/p95 for each recorded stage.
5. The actual relay produces zero unverified answers across all 36 eval cases.
   Tune near-misses with Part 4, then rerun the full project's make test.

ConsoleNotifier logs locally and returns true; this means console delivery only,
not acknowledgement from a human supervisor. Unknown/Photon notifier selection
cannot undo a deviation that has already been saved.
