# Field run — YYYY-MM-DD — wearer A/B

Status: **NOT RUN**. Copy to `YYYY-MM-DD-A.md` or `YYYY-MM-DD-B.md` only for an actual run.
Use a session suffix for repeated runs; keep all earlier evidence.

- Date/time (PT):
- Wearer letter (no name):
- Motion-trial consent / permission to retain scripted audio:
- Packed app commit / relay version / deployment origin:
- Phone OS / Even app version / glasses firmware version (read only):
- Condition: quiet / cafe; noise source, placement and level:
- Required dependencies: M9 deployed? clarify/scope from Parts 1+2 available?
- Interruptions / missing evidence:

## IMU

| Pace | Still fixture | Hz | dt median / p95 (ms) | Burst fraction | Gaps |
|---|---|---|---|---|---|
| P100 | NOT RUN | | | | |
| P500 | NOT RUN | | | | |
| P1000 | NOT RUN | | | | |

Selected pace and detector-parameter snapshot:

| Activity | Fixture | Observed duration | Intended / detected nods | False triggers | Pass / missing |
|---|---|---|---|---|---|
| Still, 120 s | | | | | NOT RUN |
| 20 double nods | | | | | NOT RUN |
| Bench work, 1800 s | | | | | NOT RUN |
| Walking, 120 s | | | | | NOT RUN |
| Talking/nodding, 120 s | | | | | NOT RUN |

Attach all 20 observer trial times and matched events; nod completion -> LISTENING timings.
Acceptance: >=19/20 intended trials; <=1 false trigger/30 min bench work; LISTENING <300 ms.

## STT and endpointing

For every ID in [the 40-line bank](README.md#speech-script-40-lines), add a row. Record the
transcript before scoring routing or answer quality. Do not replace failed transcripts.

| ID | Actual transcript | Reference / critical tokens | S / D / I | Screen / parsed command | Speech end -> screen (s) | Evidence / issue |
|---|---|---|---|---|---|---|
| | | | | | | NOT RUN |

- Commands exact: __/6; correct parsed commands: __/6.
- Question words: N=__; S=__; D=__; I=__; accuracy=__.
- Critical number/unit/drink-name words: N=__; S=__; D=__; I=__; accuracy=__ (N/A if N=0).
- Supplemental vocabulary trials (oz/pumps/degrees Fahrenheit/ppm), separately scored:
- No speech, 3 s close / no network ask:
- Speech then quiet, 800 ms endpoint (once):
- Continuous noise/speech, 8 s cap:
- Grinder holds mic open / false speech:
- Consented audio retained? Path or “not retained”:

## M10 loop and task flow

- Five SOPs opened (201/202/210/220/230), correct sections and scope:
- Clarifying questions: __/15 verified and returned to the same step.
- Taps required (target 0):
- Navigation commands, repeat and picture behavior:
- “Which drink?” -> cappuccino -> answer:
- Next-step p50 (all timings attached; target <1.2 s):
- Answer p50 (all timings attached; target <=3 s):
- Pair -> claim -> assign -> TASK_READY -> steps -> portal progress -> diagram:
- Two-minute airplane mode: progress retained / duplicates:
- Lens photos: STEP/picture, DETAILS page 2, answer/picture, warning, CLARIFY, two-tile DIAGRAM:
- 14 px labels, °/×/½, indoors / near window:
- Tile 1 / tile 2 BLE upload time:
- iOS / Android WebView (height/scroll/safe areas/dark/picture/clarify/typed fallback):

## Findings and follow-up

| Owner | Reproduction / expected / actual | Photo / log | Fix or shared handoff |
|---|---|---|---|
| | | | |

Overall: NOT RUN / FAILED / PASSED. Name missing evidence; never fill measurements from mocks.
