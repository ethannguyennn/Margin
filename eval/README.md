# Quality evaluation

Run python eval/run_eval.py against a running relay. The default origin is
http://127.0.0.1:8000; use --base-url for another origin and --output for a JSON
report. qa.jsonl is the demo bank's 45 questions (the team's list, kept verbatim at the
repo root as qa.jsonl; the Ember & Oak SOPs it asks about are in corpus/):

- 36 answerable lookups spanning SOP-201, 202, 210, 220 and 230 (all revision C).
- 3 near-misses whose topic is nearby but whose answer is absent (pumpkin spice latte,
  ice machine cleaning, bleach concentration).
- 2 ambiguous questions requiring not_found plus needs_clarification=true (the supplied
  list says "clarify"; the relay reports ambiguity this way).
- 4 off-domain questions requiring not_found.

The previous industrial HX-2 bank (36 questions over SOP-101..140) is kept as a test
fixture in relay/tests/fixtures/ (hx2-qa.jsonl, hx2-corpus/) for the relay's unit tests.

Every request uses text with audio=null and a fresh UUID session. The expected
revision in qa.jsonl is an assertion, not a forced retrieval revision; an
optional request_revision field is the only way to force a revision.

## Metrics

- Answered-correct rate: correct answers / all answerable questions. Correct
  requires the expected document, revision and section, all must_contain values
  in the displayed glance/body, and passing citation checks.
- not_found precision: expected refusals / all returned not_found responses.
- not_found recall: returned not_found / all questions expecting not_found.
  Clarification compliance is also checked per case and in category totals.
- Citation-verification pass rate: audited answers / all answered responses.
  Auditing requires verified=true, valid citation identity, a nonempty quote
  present in the local corpus after glyph/whitespace normalization, an approved
  default revision (or the explicit override), display caps, and supported
  numbers/units. It does not prove that arbitrary prose claims are entailed.
- Median latency: observed HTTP round-trip milliseconds, including failed
  requests. This is not hardware end-of-speech-to-lens latency.

A verified answer may put the whole answer in `glance` and leave `body` empty,
as the v2 generator prompt specifies. The evaluator requires a visible glance
and still audits every number and source citation independently. The 2026-10-18
pre-alignment live report is retained as historical failure evidence; the six
flagged questions were rechecked with saved responses after this correction.

## Retrieval gate calibration

```powershell
$env:PYTHONPATH = 'relay/src'
.venv/Scripts/python.exe eval/tune_gate.py --output eval/results/gate-calibration.json
```

This uses the normalized `eval/qa.jsonl`, live query embeddings and read-only
cloud retrieval. It performs no generation and changes no environment setting.
The candidate gate preserves every answerable and clarification case; among
those candidates it maximizes cheap refusals. The report records the model,
dimension, bank and per-case scores. It is development-bank calibration, not
independent evaluation; rerun when the bank or embedding model changes.

## Interpreting reports

Undefined denominators print N/A. All-refusal behavior cannot claim perfect
citation coverage. HTTP/transport failures count as failed cases. Every
response must carry a trace_id. A non-2xx answered body is still inspected for
unverified content.

Exit codes: 0 = all cases pass; 1 = quality/contract/transport failure or no
usable relay; 2 = at least one unverified answer. Fixture/mock results require
--allow-mock and are always labeled MOCK/FIXTURE ONLY, never live evidence.
The health endpoint must explicitly identify mock mode.

Independent harness tests use answer-key fixtures; their percentages are not
retrieval/generation quality numbers. Actual live evidence is explicitly labeled
in the saved JSON. On 2026-10-18, the 45-case run was incomplete as a quality
gate: generation hit HTTP 429 starting at case 18, and the pre-alignment evaluator
also rejected glance-only answers. Keep that report as failure evidence.
The six flagged questions were rerun using `gemini-3.8-flash` after alignment:
6/6 passed with 0 unverified answers; 3 had empty bodies. The responses are saved
in `results/2026-10-18-glance-only-recheck.json`. This subset does not establish
full-bank quality or sustained quota, and its 7148 ms median is not a latency pass.

# v3 loop evaluation

The original 45 coffee questions remain first in `qa.jsonl`. Eighteen additional cases cover
five scoped walkthroughs, five clarify/reply conversations, five contextual follow-up
conversations and three picture questions. `turns` reuse the case's session ID; distinct cases
use independent sessions. Each turn is scored, including clarify options, source citations,
walkthrough section/scope and expected graphic IDs. Empty-body, verified glance-only answers
are valid. The scorer independently checks every quote against approved corpus text.

Run deliberately against a live relay, with pacing for the shared provider quota:

```bash
PYTHONPATH=relay/src python eval/run_eval.py --base-url https://getyourassto.work --pace 10 --output eval/results/YYYY-MM-DD-v3.json
PYTHONPATH=relay/src python tools/diagnostic/gap_probe.py --relay https://getyourassto.work --pace 10
PYTHONPATH=relay/src python tools/diagnostic/clarify_rate.py --relay https://getyourassto.work --pace 10 --output eval/results/YYYY-MM-DD-step-regression.json
```

The gap probe is safe to import, refuses mock evidence, and exits nonzero on failed or missing
checks. Reports include timestamps and model identifiers when verbose health provides them;
missing model data is recorded as null. Offline tests are fixtures, never live quality evidence.

The step regression accepts verified glance-only answers and independently scores all 18
responses, rather than applying the obsolete empty-body error rule. It is safe to import.
The till walkthrough uses the plan's explicit till-closing phrase; a generic closing checklist
can also refer to back-of-house closing. Cleaning is SOP-210 5.1-5.4, distinct from closing 6.x.
The generic milk-temperature lead-in checks the 160 degF maximum; individual milk targets
differ, so a correct whole-milk answer need not include the soy/oat lower bound of 140 degF.

Live-run scoring corrections retain all 45 original questions and required values. Unit spelling
and HTML degree entities are normalized without changing values or units. `a24` also accepts
"under back counter" (the same location with the article omitted); "above" still fails. `a25`
accepts the approved shot-time specification table in 2.1 as well as the procedure in 3.5.
`a05` accepts the price table's "not sold" answer for a Large flat white; `a08` accepts
"black" plus "counterfeit" for the black-mark question; `a27` accepts the matching
troubleshooting row in 5.1. Markdown table cell separators are formatting, not facts.
These alternatives are explicit annotations and have wrong-fact regression tests. Historical
reports keep their original scores; reruns identify the new scorer/code revision.
