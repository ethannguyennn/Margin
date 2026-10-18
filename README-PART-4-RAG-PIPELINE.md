# Part 4 — Retrieval, Grounded Generation & The Trust Layer

**Branch:** `part-4-rag-pipeline`
**Owns:** the part of Margin that is actually novel. Transcription, intent,
hybrid retrieval, grounded generation, and the deterministic citation
verifier that lets us say "if it is not in the approved documents, the lens
says so instead of guessing."

**Milestone:** M4. The verifier is the product thesis. A wrong answer with a
confident citation is worse than no answer, so `not_found` is a success state.

---

## 1. Files you own

```
relay/src/margin_relay/pipeline/transcribe.py   # GeminiTranscriber + MockTranscriber
relay/src/margin_relay/pipeline/intent.py       # rule-based classifier
relay/src/margin_relay/pipeline/retrieve.py     # hybrid search + RRF
relay/src/margin_relay/pipeline/generate.py     # grounded structured generation
relay/src/margin_relay/pipeline/verify.py       # citation verifier (no LLM)
relay/src/margin_relay/pipeline/sanitize.py     # glyph rules, mirror of the app's
relay/tests/test_intent.py
relay/tests/test_retrieve.py     # RRF merge, thresholds
relay/tests/test_verify.py       # quote present / absent / fuzzy / numbers
relay/tests/test_sanitize.py     # same fixtures as app/tests
relay/tests/fixtures/            # a recorded 16 kHz PCM clip for the STT path
```

## 2. Files you must NOT touch

`main.py`, `config.py`, `schemas.py`, `routes/`, `obs.py`,
`pipeline/mock.py`, `Makefile`, `.env.example` (Part 3); `db.py`, `db/`,
`corpus/`, `eval/`, `notify/` (Part 5); all of `app/` (Parts 1 and 2); and
**`main`**.

If you need a new env var, post the name and default in the channel — Part 3
adds it to `config.py` and `.env.example`.

## 3. Your dependencies

- Part 3 pushes `scaffold-relay` in the first hour (`config.py`,
  `schemas.py`, the pipeline `Protocol`s). Then:
  `git fetch --tags && git merge scaffold-relay`
- Part 5 pushes `db.py` and the seeded corpus. Until then, **do not wait**:
  every module here is unit-testable against hand-written chunk dicts, and
  `retrieve.py` takes a connection pool as an argument rather than importing
  one. Write the tests first; they are the deliverable that proves this part.

---

## 4. Interfaces you implement (Part 3 calls exactly these)

```python
class Transcriber(Protocol):
    async def transcribe(self, pcm: bytes, sample_rate: int) -> str: ...

def classify_intent(transcript: str) -> Intent: ...

class Retriever(Protocol):
    async def retrieve(self, query: str, revision: str | None) -> RetrievalResult: ...
    async def steps_for(self, doc_id: str, revision: str | None) -> list[Step]: ...

class Generator(Protocol):
    async def generate(self, query: str, chunks: list[Chunk]) -> Draft: ...

def verify(draft: Draft, chunks: list[Chunk]) -> VerifyResult: ...
def sanitize(text: str) -> str: ...
```

`RetrievalResult`: `chunks: list[Chunk]`, `best_sim: float`, `best_rrf: float`.
`Draft`: `answerable`, `needs_clarification`, `glance`, `body`,
`citations: list[{chunk_id, quote}]`.
`VerifyResult`: `ok: bool`, `reason: str | None`, `citations: list[Citation]`.

Exact shapes come from Part 3's `schemas.py`. Import them; never redefine them.

## 5. Transcription (`transcribe.py`)

- `GeminiTranscriber` uses `GEMINI_MODEL_TRANSCRIBE` (a current model ID —
  look it up in Google's docs, do not hardcode a guess).
- Input is raw PCM: **16 kHz, signed 16-bit LE, mono.** Wrap it into a WAV
  container in memory (`wave` from the stdlib, 44-byte header — no audio
  library needed) before sending.
- **Never write audio to disk.** In-memory buffers only, even while debugging.
- Prompt it for a plain verbatim transcript, no punctuation cleanup, no
  interpretation. Technicians say "four newton meters" and "M5" — keep it raw;
  retrieval handles the rest.
- `MockTranscriber` returns a canned string so the rest of the pipeline is
  testable with no API key.
- Timeout hard (~4 s) and raise a typed error Part 3 maps to `stt_failed`.

## 6. Intent (`intent.py`) — rule-based, no LLM, sub-millisecond

Case-insensitive regex on the transcript, first match wins:

| intent | pattern |
|---|---|
| `walkthrough` | `guide me|walk me through|step by step|take me through|start procedure` |
| `deviation` | `log (a )?deviation|report (an )?(issue|problem|nonconformance)|flag this` |
| `repeat` | `repeat|say that again|what was that` |
| `question` | everything else |

For `deviation`, also return the text with the trigger phrase stripped — that
remainder is what gets logged. Unit-test every pattern plus three phrasings
that must *not* match (e.g. "what was that torque spec" is a question, not a
`repeat`).

## 7. Retrieval (`retrieve.py`) — hybrid, and the `not_found` gate

1. Embed the transcript with `GEMINI_MODEL_EMBED` at `EMBED_DIM`
   (request 768 dims via `output_dimensionality` if the model supports it —
   **verify**, and make the dim come from config so Part 5's column matches).
2. Two queries in parallel, both filtered to `documents.status = 'effective'`
   (or the forced `revision` when one is passed):
   - vector top-20: `ORDER BY embedding <=> $q`
   - lexical top-20: `ts_rank_cd(tsv, websearch_to_tsquery('english', $q))`
3. Merge with **Reciprocal Rank Fusion**: `score = sum(1 / (60 + rank))` over
   both lists. Keep the top **6** chunks. Return text, ids and scores.
4. **The gate:** if best vector similarity < `NOT_FOUND_MIN_SIM` **and** best
   RRF score < `NOT_FOUND_MIN_RRF`, short-circuit to `not_found` and **do not
   call the LLM.** This is the cheapest and most reliable refusal, and it is
   also 1.2 s of latency saved on every off-document question in the demo.
   Tune both thresholds against Part 5's `eval/qa.jsonl` near-miss cases.
5. `steps_for(doc_id, revision)` returns chunks with `is_step = true` ordered
   by `step_order`, mapped to the `Step` shape.

Unit-test the RRF merge as a pure function on two synthetic ranked lists —
that is where off-by-one bugs hide, and it needs no database.

Lexical leg: start with built-in `tsvector`/GIN. If Tiger's BM25 / `pg_text`
extension is available on our service, swap it in behind the same function
signature (**verify in the Tiger docs**).

## 8. Generation (`generate.py`) — one call, structured output

Use the SDK's response-schema feature so you get JSON, not prose. Temperature
low. `GEMINI_MODEL_GENERATE`.

System prompt — adapt the wording, keep every rule:

```
You answer questions about company procedures using ONLY the provided CONTEXT chunks.
Rules:
1. If the context does not contain the answer, return answerable=false. Never guess.
2. Every claim must be supported by a verbatim quote copied from a chunk. Cite chunk_id and quote.
3. glance: <= 60 characters, ASCII only, imperative, include the key value/unit.
4. body: <= 450 characters, ASCII only, plain sentences, no markdown.
5. Preserve numbers, units, and warnings exactly as written. Never convert units.
6. If the question is ambiguous between procedures, answerable=false and needs_clarification=true.
Return JSON: {answerable, needs_clarification, glance, body, citations:[{chunk_id, quote}]}
```

Rule 5 is a safety rule, not a style rule: a unit conversion on a torque spec
is how someone strips a thread. Never "helpfully" normalize.

Generation uses `GENERATE_TIMEOUT_S` (20 s by default) for both the Gemini call
and the route guard. The app allows 50 s for two attempts plus STT/retrieval.
Timeout raises a typed error Part 3 maps to `llm_timeout`.

The implemented schema also requests `display: {kind, items} | null`. Gemini chooses
`answer`, `checklist`, or `warning` from the retrieved context. Each of 1-4 items is a
complete source sentence, at most 180 characters after sanitization, present in a
cited quote. If no complete sentence fits, it returns `display=null`. The verifier
rejects paraphrased instructions, dropped negations/conditions, and changed signs
or comparisons. Rejected cards follow the same one-retry/refusal path as answer text.
The relay returns this optional field only with a verified answer; repeat preserves it.
Older clients can ignore it and older relays can omit it.

The lens opens checklist/warning cards immediately, one complete item per swipe,
followed by ordinary answer details. The phone renders the same card with citations.
The SDK's three native text containers and existing gestures remain in use; Gemini
selects a supported presentation, with no executable HTML or arbitrary SDK commands.
Walkthroughs still use the approved corpus step order rather than generated steps.

### Accompanying reference images

`corpus/illustrations.json` links inspected synthetic reference drawings to exact
SOP sections and revisions. The five generated PNGs live in `app/src/assets/sops/`;
`corpus/illustration-prompts.json` records their generation and edit prompts.
`build_prompt` offers only references supported by the retrieved chunks. Gemini
returns `graphic_id`; the verifier rejects unknown IDs and references not supported
by a citation containing the catalog's source quote. It never accepts model URLs.

The app packages the images locally. It uses the same source picture and crop on
the phone and glasses, with a 288x144 native image container beside the text.
High-contrast Gray8 pixels are sent through `updateImageRawData`; image entry/exit
uses `rebuildPageContainer`. Longer instructions paginate at the narrower text
width. Old references are cleared before changing steps so an upload failure cannot
pair an old picture with a new instruction. Walkthrough steps receive matching
references directly from their corpus section. Older relay responses can resolve
the same references from their cited section when the new field is absent.

## 9. Verification (`verify.py`) — deterministic, no LLM, the whole thesis

A draft passes only if **all** of these hold:

1. Every `citations[].chunk_id` is in the retrieved set.
2. Every `quote` appears in that chunk's text after normalization: lowercase,
   collapse whitespace, strip punctuation differences. Allow a small fuzzy
   ratio (**>= 0.95**, `difflib.SequenceMatcher` from the stdlib) to tolerate
   spacing noise.
3. Every number+unit token appearing in `glance` or `body` also appears in at
   least one cited quote. Tokenize numbers with their adjacent unit
   (`4 N-m`, `M5`, `30 s`, `70 %`) — a fabricated torque value is the exact
   failure mode this catches.

On failure: retry generation **once**, passing the failure reason back into the
prompt. If it fails again, `outcome = "not_found"`. **Unverified text is never
displayed.** `verified = true` only on a pass.

Test matrix (write these before the implementation):

- quote present verbatim -> pass
- quote present with different whitespace/case -> pass
- quote absent / hallucinated -> fail
- quote from a chunk that was not retrieved -> fail
- glance contains `5 N-m` while the quote says `4 N-m` -> **fail**
- glance contains a number that appears nowhere in any quote -> fail
- body quotes correctly but converts `4 N-m` to `35 in-lb` -> fail

## 10. Sanitize (`sanitize.py`) — must match the app byte for byte

Same rules as Part 1's `app/src/ui/glyphs.ts`, **same test fixtures**. Agree
the fixture list with Part 1 in the channel and copy it verbatim into both
test suites.

| In | Out |
|---|---|
| section sign | `Sec ` |
| middot, bullet | `-` |
| degree sign | ` deg` |
| micro sign | `u` |
| ohm sign | ` ohm` |
| en dash, em dash | `-` |
| curly double / single quotes | `"` and `'` |
| multiplication sign | `x` |
| plus-minus sign | `+/-` |
| >= and <= signs | `>=` `<=` |
| right arrow | `->` |
| emoji / any other non-ASCII not allow-listed | dropped |

Allow-listed non-ASCII, one module-level constant:

```
U+25B2 U+25B3 U+25B6 U+25B7 U+25BC U+25BD U+25C0 U+25C1
U+25CF U+25CB U+25A0 U+25A1 U+2605 U+2606
U+2501 U+2500 U+2588 U+2587 U+2586 U+2585 U+2584 U+2583 U+2582 U+2581
U+256D U+256E U+256F U+2570 U+2502
```

The G2 has one firmware font; anything outside it is silently dropped on the
lens, so sanitizing server-side is what stops a spec reading "torque to 4 -m".

## 11. Build order

1. `sanitize.py` + `intent.py` with full tests. Pure functions, no deps, done
   in the first hour, and they unblock nothing but they also never break.
2. `verify.py` + its test matrix against hand-written chunk dicts.
3. `retrieve.py`: RRF as a pure function with tests, then the two SQL queries
   once Part 5's schema and `db.py` land.
4. `generate.py` against 6 hardcoded chunks, asserting the JSON schema.
5. `transcribe.py` with the recorded PCM fixture.
6. Threshold tuning against `eval/qa.jsonl` with Part 5.

## 12. Acceptance (M4 done)

- [ ] `make eval` shows **zero unverified answers displayed**.
- [ ] Documented `not_found` precision/recall from `eval/qa.jsonl`, including
      the near-miss cases.
- [ ] Off-document question returns `not_found` **without an LLM call** (assert
      it with a call counter in the test).
- [ ] A forced hallucination (monkeypatched generator) is caught by `verify`
      and degrades to `not_found`.
- [ ] `test_sanitize.py` and `app/tests` agree on every shared fixture.
- [ ] Citations always carry `doc_id`, `revision`, `section` so Part 1 can
      render `"SOP-114 Sec 4.2 rev C"`.
- [ ] `make test` green.

## 13. Stretch (only after M4 is green): revision forks

Tiger zero-copy fork with SOP rev D loaded, exposed as `DATABASE_URL_FORK`
(**verify the Tiger CLI fork syntax in their docs**). Run retrieval against
both; when the cited step text differs, append `Changed in rev D` to `glance`.
Keep it behind a config flag — it must not be able to break the main path.

## 14. Merge protocol (read once, it is short)

1. **Never commit to `main`.** `main` stays empty until the integration merge.
2. Commit and push to your own branch constantly. Small commits.
3. Pull `scaffold-relay` from Part 3 when announced; pull Part 5's branch when
   `db.py` and the seeded corpus are ready.
4. Stay inside **Files you own**. If you need a change in someone else's file,
   post a one-line request in the channel; do not edit it.
5. Integration order into `main`: 1, 3, 2, 4, 5.
6. Do **not** add `Co-Authored-By: Claude` to commits.

## 15. House rules

- Never persist raw audio. In-memory only, then dropped.
- All keys come from Part 3's config. Never read `os.environ` directly and
  never log a key or a full prompt containing one.
- Synthetic SOPs only. Never ingest real employer documents.
- Never show unverified text as an answer. If you are ever unsure, return
  `not_found` — the refusal is the feature.
