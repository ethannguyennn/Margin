# Part 4 field protocol

Status: preparation only. No real recordings, wearer detection rates, cafe STT scores,
on-lens latency or BLE timings have been measured in this worktree. M10 remains open.
Use [RUN-TEMPLATE.md](RUN-TEMPLATE.md) for each wearer/session; do not label an offline pass
as a field pass. This follows `README-V3-PART-4-FIELD-HARDWARE.md` and `BUILD-PLAN-V3.md`.

## Before a run

- Use wearer **A** or **B**, never names or initials that identify a person. Both consent to
  the trial; separately record whether retaining scripted audio is permitted. No customers
  or customer voices. No changes to the loaned glasses or firmware.
- Record the packed app's commit hash, relay version, phone OS/Even app version and the noise
  condition. Part 3 supplies the VM `.ehpk`; local sideload instructions are in `deploy/README.md`.
- For IMU acquisition, run `cd app` then `npm run dev -- --host` and open the live build on
  the paired phone with `?dev=1`. The phone must use the laptop's LAN address, not localhost.
  Mock mode must be off and the URL must have no `?imu=` replay. The simulator has no G2 IMU.
- Keep the WebView foregrounded and the phone awake. Background gaps invalidate a continuous
  duration trial: record the failure and repeat it. Do not count elapsed timer time as recorded motion.
- The shared Gemini key remains rate-limited: coordinate any live run with Part 3 and pace
  requests to its budget. Do not run the live diagnostic scripts just to print the script below.

## IMU recordings

For each wearer, first record stillness for 30 s at each of P100, P500 and P1000. Copy the JSON
and record `meta.summary.hz`, `dt_median_ms`, `dt_p95_ms` and `burst_frac` in the run report.
These pace values are protocol codes, not literal Hz. The recorder holds the selected pace;
normal live operation still probes for a suitable pace when no recording is active.

At the candidate pace, each wearer records:

| Activity | Duration / observed action | Evidence |
|---|---|---|
| still | 120 s | False NOD/SHAKE counts |
| double-nod | 20 deliberate double nods, spaced at least 3 s apart | Observer's 20 trial times and matching detector events |
| bench-work | 1800 continuous seconds: wiping, reaching, looking at counter/till | Observer marks unintended triggers and any deliberate nods |
| walking | 120 s | False triggers and data gaps |
| talking-nodding | 120 s, scripted speech plus deliberate/ordinary conversational nods | Label which nods are intended commands |

The recorder supports 3–1800 s, shares the stream with the live detector, and includes its
effective detector parameters in `meta.params`. It exports motion only. Copy JSON after each
run; it is not uploaded or saved by the app. Inspect before saving:

1. Samples must be nonempty and cover the intended interval without foreground gaps. Compare
   the last sample's `t` and `summary.seconds` with the requested duration. A low rate or large
   `dt_p95_ms` needs investigation; do not silently trim gaps or synthesize missing samples.
2. Save as `app/tests/motion/fixtures/<activity>.<A-or-B>.P<pace>.g2.json` with `meta.source: "g2"`.
   Add observed deterministic replay counts, e.g. `"expect": {"NOD": 19, "SHAKE": 0}`, plus
   the attempted nod count and observation times in the report. Never change the attempted
   count to match the detector. Counts alone cannot prove 19 distinct intended trials were detected.
3. `npm test -- tests/gestures.test.ts` picks up the recording. The saved `meta.params` pins the
   recording's effective settings. When evaluating a tuning change, explicitly update that
   snapshot in the evaluation copy and report both parameter sets; preserve the original raw samples.
4. Tune defaults/calibration only from real evidence and rerun all recordings and existing tests.
   Record replay counts in `meta.expect` only after checking event-to-trial matches in the report;
   a passing replay is not itself an acceptance measurement.

Acceptance per wearer: at least **19/20** intended double nods detected, no more than **one
false trigger per 30 min bench work**, and nod completion to LISTENING **under 300 ms**.
Use an observer/video timeline for nod completion and the first LISTENING frame; the replay
event timestamp alone does not measure UI latency. Attach the matched trial timings.

## Speech script: 40 lines

Run all 40 through the **glasses mic**, for A and B, in quiet and cafe noise: four runs,
160 utterances. Use grinder, steam and normal music as the noise condition; describe placement
and level consistently. Never record bystanders. Read each line exactly as written.

Rows 1–16 and 17–34 come from `voice_loop.py` and `clarify_rate.py` (the latter repeats its six
questions three times). Rows 35–40 are the ambiguity, chained-follow-up and picture probes from
`gap_probe.py`. Keep the same session and cappuccino milk-step context for 37–39. These are
script references; do not import `gap_probe.py` or `clarify_rate.py`, which run live at import.

| ID | Spoken reference | Context / expected behavior |
|---|---|---|
| o1 | walk me through getting the register ready before my shift | SOP-201 |
| o2 | take me through closing out the till at the end of the night | SOP-202 |
| o3 | guide me through the kitchen opening checklist | SOP-210 |
| o4 | show me how to pull a good espresso shot | SOP-220 |
| o5 | walk me through making a cappuccino | SOP-230, cappuccino scope |
| n1 | I need to do the cash count for closing | SOP-202 |
| n2 | pull up the espresso standards | SOP-220 |
| n3 | open the cleaning procedure | SOP-210 |
| n4 | let's start the back of house opening | SOP-210 |
| x1 | walk me through changing a flat tire | Refuse off-topic |
| c1 | next | SOP-210: next |
| c2 | okay I'm done with that one | SOP-210: next |
| c3 | go back | SOP-210: back |
| c4 | what's next | SOP-210: next |
| c5 | say that again | SOP-210: repeat |
| c6 | show me the picture | SOP-210: picture |
| q1a | what temperature should the fridge be at | SOP-210 3.2 |
| q2a | what do I do if it's too warm | SOP-210 3.2 |
| q3a | how long does it need to warm up | SOP-210 3.3 |
| q4a | what concentration should the sanitizer be | SOP-210 3.7 |
| q5a | how often do I replace it | SOP-210 3.7 |
| q6a | where does the scoop go | SOP-210 3.6 |
| q1b | what temperature should the fridge be at | SOP-210 3.2 |
| q2b | what do I do if it's too warm | SOP-210 3.2 |
| q3b | how long does it need to warm up | SOP-210 3.3 |
| q4b | what concentration should the sanitizer be | SOP-210 3.7 |
| q5b | how often do I replace it | SOP-210 3.7 |
| q6b | where does the scoop go | SOP-210 3.6 |
| q1c | what temperature should the fridge be at | SOP-210 3.2 |
| q2c | what do I do if it's too warm | SOP-210 3.2 |
| q3c | how long does it need to warm up | SOP-210 3.3 |
| q4c | what concentration should the sanitizer be | SOP-210 3.7 |
| q5c | how often do I replace it | SOP-210 3.7 |
| q6c | where does the scoop go | SOP-210 3.6 |
| f1 | How many pumps of syrup? | Ambiguous: which drink? |
| f2 | How hot? | Ambiguous: ask to clarify |
| f3 | How hot should the milk be? | Cappuccino milk step |
| f4 | And for a kids drink? | Same session and step as f3 |
| f5 | What about extra hot? | Same session and step as f3 |
| f6 | What does the steam wand look like? | Milk step, reference picture |

For each row record the actual transcript before evaluating routing or answer correctness.
Normalize case and punctuation for comparison, but preserve words, numbers, units and drink
names. Commands must match all six spoken references per run; separately record the parsed
command. For questions, align reference and transcript words and count substitutions,
deletions and insertions: word accuracy = `max(0, 1 - (S + D + I) / reference_word_count)`.
Report overall accuracy and a separate alignment/count for numbers, units and drink names;
the latter must reach **95%**. If a subset has no reference tokens, report **N/A**, never 100%.
The fixed bank sparsely exercises units/numbers: add clearly labelled supplemental scripted
questions containing oz, pumps, degrees Fahrenheit and ppm; report their scores separately.
An SDK fake only checks request wiring; it does not demonstrate STT accuracy or noise robustness.

Keep audio only when everyone recorded consented, only under `tools/diagnostic/wav-field/`.
WAV/PCM files are ignored by Git; do not force-add them without that consent. Otherwise retain
only anonymous transcripts, scores and timing measurements. The runtime app still never saves audio.

Test endpointing separately in each noise condition: no spoken words for 3 s -> mic closed,
no ask; speech then 800 ms of quiet -> one endpoint; sustained speech/noise -> mic closed by
the 8 s cap. Note whether grinder noise is mistaken for speech or prevents the silence endpoint.
Leave thresholds unchanged until these observations exist.

## Full on-device run (after M9)

Use the packed VM build. Double nod and say “walk me through closing out the till”; verify
SOP-202 7.1. Navigate by all six commands. At the count step, ask “what do I do if it's over?”;
verify a cited answer and return to the same step. Ask “How many pumps of syrup?”, answer
“cappuccino” to the clarification, and check the resulting answer. Show an illustrated step's
picture. Repeat opening SOP-210, SOP-220, scoped SOP-230 and SOP-201. Per wearer: **five SOPs,
15 clarifying questions, zero taps**. Record every utterance/screen/end-of-speech latency;
require next-step p50 < 1.2 s and answer p50 <= 3 s. Clarify/scope checks depend on Parts 1+2.

Photograph STEP with reference picture, STEP_DETAILS page 2, answer with picture, warning,
CLARIFY and a two-tile relay DIAGRAM. Check 14 px labels, indoor/window light, °/×/½ coverage;
measure each BLE tile independently. Photograph only synthetic content, with consent.

Pair on lens -> claim in portal -> assign SOP-210 -> TASK_READY -> double nod -> steps ->
portal progress -> show diagram. Toggle airplane mode for two minutes mid-task, then verify
progress survives and is not duplicated. Record CORS failures for Part 3. On iOS and Android,
check WebView height/scroll/safe areas/dark theme/answer picture/clarify chips/typed fallback.
File UI issues with screen + photo to Part 1, relay issues to Part 2, deployment issues to Part 3
using the shared handoff protocol. They own source fixes and TODO updates outside Part 4.
