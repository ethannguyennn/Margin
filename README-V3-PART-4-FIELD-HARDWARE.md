# Part 4 v3 — Field & hardware: prove the loop on real glasses

**Branch:** `v3-part-4-field-hardware` (from tag `v3-base`)
**Owner:** _____
**Read first:** `BUILD-PLAN-V3.md` (§1 where the loop stands, §3 milestones),
`docs/handoffs/PART-2.md` (IMU semantics, detector, endpointing, the recorder).
**Owns:** everything that only real hardware can answer: the double nod on real heads, the
glasses microphone and speech recognition in noise, legibility of text and pictures on the
lens, the v2 task flow on device, and the phone WebView. You turn what you find into fixtures,
tuned parameters and bug reports with evidence.
**Milestones:** M10 (the field script passes on two wearers). Early field runs from day 2 on
`v3-base` builds so the other parts get findings while they still have time.

---

## 0. Setup

```bash
git fetch && git switch v3-part-4-field-hardware
cd app && npm ci && npm test
npm run dev -- --host            # ?dev=1 shows the IMU recorder (docs/handoffs/PART-2.md §1)
```

Sideload: `deploy/README.md` "Local hardware sideload". Use Part 3's packed `.ehpk` for field
runs (it points at the VM); note its commit hash in every report. Glasses are loaned: no
firmware changes, no modifications.

## 1. Files you own

```
app/src/motion/{gestures,imu,record}.ts
app/src/audio/{capture,vad}.ts
relay/src/specs_relay/pipeline/transcribe.py        # STT prompt + vocabulary (retry: ed2d983)
app/tests/{gestures,audio,vad}.test.ts, app/tests/motion/** (fixtures: real recordings)
relay/tests/test_transcribe.py
docs/handoffs/PART-2.md, docs/field/**              # field protocol + results, one file per run
tools/diagnostic/wav-field/                          # recorded field utterances (no names, synthetic content only)
```

## 2. Files you must NOT touch

`app/src/state.ts`, `app/src/ui/**`, `app/src/phone/**` (Part 1; file the issue with a photo);
`routes/ask.py`, `pipeline/{generate,retrieve,verify,intent}.py` (Part 2); `deploy/**`,
`client.ts`, `settings.ts`, `app.json` (Part 3).

## 2a. Privacy for recordings

IMU recordings are motion only. Field audio for STT tests is the team reading the scripted
lines in §4.2, recorded with consent, no customer voices, kept in `tools/diagnostic/wav-field/`
only if everyone in it agrees; otherwise keep it local and commit only the transcripts and
scores. The app itself never persists audio (unchanged).

## 3. The work

### 3.1 Real IMU fixtures and the M4 nod numbers

**Evidence:** every fixture in `app/tests/motion/fixtures/` is `*.synthetic.json`. The detector
passes them all, and double nods worked on glasses in `61b9c1e`, but no detection rate has ever
been measured on a person (PART-2.md §6 marks each one MISSING).

**Do:** with the `?dev=1` recorder, two wearers each record: still (2 min), 20 double nods,
30 min bench work (wiping, reaching, looking down at a counter, at the till), walking (2 min),
talking while nodding. Commit them as `*.g2.json` with `meta.expect`. Make `gestures.test.ts`
run them. Tune `DEFAULT_PARAMS` / calibration until: double nod >= 95 % (19/20) per wearer,
<= 1 false trigger per 30 min bench work, nod -> LISTENING < 300 ms. Record samples/s per pace
code (P100/P500/P1000) in PART-2.md.

### 3.2 Speech recognition on the glasses mic, in noise

**Evidence:** every voice test so far used clean synthesized speech (Windows SAPI) or a quiet
room. `TRANSCRIBE_PROMPT` still uses HX-2 examples ("M5", "four newton meters"); the coffee
bank needs "oz", "pumps", "°F", "ppm", drink names.

**Do:** a script of 40 lines (the 10 open prompts, 6 commands, 18 clarifying questions and 6
follow-ups in `tools/diagnostic/voice_loop.py` / `gap_probe.py`) read by two wearers through
the glasses mic, quiet and with cafe noise (grinder, steam wand, music at a normal level). Score
transcripts: commands must be exact (6/6 per run), questions >= 95 % word accuracy on numbers,
units and drink names. Update the STT prompt with coffee vocabulary; add the recorded
transcripts' failures as `test_transcribe.py` cases where possible. Also: the 3 s no-speech
close, the 800 ms endpoint and the 8 s cap in noise (does the grinder hold the mic open?).

### 3.3 The field script (M10)

Run the full loop on the VM build, per wearer, in a cafe-like setting:

1. Double nod -> "walk me through closing out the till" -> lands on 7.1 (SOP-202).
2. Step through by voice ("next", "okay I'm done", "go back", "what's next").
3. On the count step: "what do I do if it's over?" -> verified answer -> back on the step.
4. "How many pumps of syrup?" -> "Which drink?" -> "cappuccino" -> answer (after Parts 1+2 land).
5. "Show me the picture" on an illustrated step -> picture legible.
6. Repeat with SOP-210 opening, SOP-220 espresso shot, SOP-230 cappuccino (scoped), SOP-201.
7. Per wearer: 15 clarifying questions in total, 5 SOPs opened, 0 taps needed.

Record per step: transcript, screen reached, seconds from end of speech, any confusion.
Results in `docs/field/YYYY-MM-DD-<wearer-initials>.md` with photos of the lens.

### 3.4 Lens legibility

Photograph on the lens: STEP with a reference picture, STEP_DETAILS page 2, an answer with a
picture, a warning line, CLARIFY (once Part 1 lands it), a two-tile relay DIAGRAM (the v2
conversion tiles in `eval/conversion/results/2026-10-17-gemini-3.8-flash/tiles/`) and BLE time per tile.
Check: 14 px diagram labels, brightness indoors and near a window, font coverage (°, ×, ½).
File each problem to Part 1 with the photo and the screen name.

### 3.5 The v2 task flow on device

**Evidence:** no `/v1/devices/*`, `/v1/assignments/*`, `/v1/progress` or `/v1/diagrams/*`
traffic from real glasses yet (TODO §3).

**Do:** pair code on the lens -> claim in `/portal/` -> assign SOP-210 -> TASK_READY -> double
nod -> step through -> progress on the portal board -> "show diagram". Note CORS rejections in
the relay log (Part 3 can pull it). 2 min airplane mode mid-task: progress must survive.

### 3.6 Phone companion in the Even app WebView

iOS and Android: height, scrolling, safe areas, dark theme, the answer view with picture, the
clarify chips (after Part 1), the typed-ask fallback. Issues to Part 1 with screenshots.

## 4. Build order

Day 2: 3.1 recordings + 3.2 transcripts on the `v3-base` build (findings feed Parts 1 and 2
early). Then 3.4, 3.5, 3.6. 3.3 once M9 is deployed; repeat it after every main deploy.

## 5. Acceptance (M10)

- Real `*.g2.json` fixtures committed; `npm test` runs them; >= 95 % double nods per wearer,
  <= 1 false trigger / 30 min bench work, nod -> LISTENING < 300 ms.
- STT: 6/6 commands exact per run in noise; >= 95 % word accuracy on numbers, units and drink
  names across the 40 lines; prompt updated and tested.
- The field script passes for two wearers with 0 taps; `"next"` p50 < 1.2 s end of speech ->
  new step; answer p50 <= 3 s.
- Every legibility, WebView and task-flow problem found is either fixed by its owner or listed
  in `TODO.md` with a photo.

## 6. House rules

Every rule in BUILD-PLAN-V3 §5. Motion-only IMU fixtures, consented and synthetic-content audio,
no names in files. Do not touch firmware or modify the loaned glasses.
No `Co-Authored-By: Claude` in commits.
