# Specs v2 — actual native simulator evidence

SDK 0.0.16; official simulator 0.9.5; Windows WebView2; VITE_MOCK=1.
Implementation tested: `82fc3339e0f48107788416878d6f53d8faf07ecd`.

The temporary `ui/local-v2-stubs.ts` adapter supplies synthetic pairing,
calibration, endpointing, command responses, assignment and PNG tiles. These
are independent UI tests, not Part 2 IMU replay, measured head gestures,
recognized speech, a live relay, or hardware evidence.

`results.json` records 25 screen assertions, M1's zero-tap ask/20-second dim,
M2's ordered six progress events, two successful image tiles, two layout
rebuilds, root exit and a native-storage restart at STEP 3. Dev controls were
activated in the real simulator WebView; controller states were not injected.
The pairing/privacy acknowledgement is setup, outside M1's measured flow.

Captured frames wait until SDK display calls complete and allow 160 ms for
presentation. Preview PNGs composite the exported RGBA alpha mask onto black;
the original screenshots are not modified. Regenerate original captures and
full console logs under ignored `app/test-artifacts/v2/` with:

```powershell
# terminal 1, app/
npm.cmd run dev:mock:v2
# terminal 2, app/; close other simulator windows first
npm.cmd run test:simulator
```

`m2-step-1` shows a warning; `m2-step-3` shows a checkpoint and diagram hint.
`m2-diagram` shows distinct left/right tiles with 1/2 and 3/4 callouts.
`cold-start-step-3` is the actual restored step after native shutdown and
WebView reload. Text fit and diagram visibility were visually inspected here.
**Not yet tested on hardware**: glasses were unavailable.

See `docs/handoffs/PART-1.md` for full commands, SDK signatures, owner requests,
test counts and the companion's currently blocked `command` outcome maps.
