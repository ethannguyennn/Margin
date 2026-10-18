# Live glasses display

Specs 0.4.4 adds a workspace-scoped, read-only display feed to both web apps.
Open `/app/#/lens` or `/portal/#simulator`, choose **Live glasses**, then select
the worker's device. The browser and the glasses must join the same workspace.
Run the updated app on the G2 in the foreground. Old installed packs cannot
publish the feed; install `app/specs.ehpk` from this build or use the updated
hosted app through the Even Hub development QR workflow.

The browser receives content acknowledged by the SDK, including two diagram
tiles and reference-image fallback. It reconstructs the layout using shared
576x288 container geometry. This is not an optical capture or pixel readback;
firmware font metrics can differ. Browser simulation remains a separate mode
and never publishes its controller into the device feed. VITE_MOCK builds do
not publish. No new SDK method is used.

Publishing is coalesced to at most two requests/second, with a heartbeat every
three seconds. HTTP is serialized independently of the Bluetooth BridgeQueue;
network failure never delays a glasses render. Backgrounding pauses publishing;
returning to foreground publishes after the next acknowledged draw. Closing
aborts outstanding requests. Missing heartbeats mark the feed offline after
12 seconds, with the last received frame explicitly labeled stale. Failed draws
pause the feed instead of claiming a queued frame reached the glasses.

Authentication uses existing device tokens for publishers and joined worker
browsers, or existing portal workspace auth for admin viewers. Tokens never enter
URLs. Both list and frame reads recheck current workspace membership. Moving a
device hides its old workspace frame. Stream IDs plus increasing sequence numbers
reject late updates and superseded app launches. Relay restart recovery reopens
the stream. Responses use `Cache-Control: no-store`.

The relay keeps only the latest frame per device in bounded process memory
(256 sources; frames expire after ten minutes). It does not save display content,
audio, IMU data, or a display history to the database. This implementation needs
one relay worker, as deployed today. Before scaling to multiple processes or
replicas, replace the in-memory store with a shared expiring cache. Input is capped
at 200 KB, text fields at 2,000 characters and diagram data at two 288x144 PNG/raw
grey tiles. Viewer polling is one request chain in flight, once per second.

## Validation

`mingw32-make test`: 899 relay passed / 13 skipped; 634 app passed / 12 skipped;
10 portal passed. Both production builds pass. Targeted feed/display tests pass
after the final adjustments. Existing dynamic/static client import warning remains.
Evidence: `app/tests/evidence/display-sync/`. Cross-browser tests used a labeled
synthetic publisher over real HTTP against MOCK_MODE=1, not physical glasses.
Hardware synchronization and legibility: **not yet tested on hardware** (glasses
unavailable). No live-relay physical-glasses result is claimed.

## Reproduction

```powershell
mingw32-make test
npm --prefix portal run build
# Build/pack against the deployed relay, not local mock settings:
$env:VITE_MOCK = '0'
$env:VITE_RELAY_ORIGIN = 'https://getyourassto.work'
$env:VITE_ASK_TIMEOUT_MS = '50000'
npm --prefix app run pack
```

Install/open the updated app through Even Hub with the G2 connected. Enter the
workspace code in the Lens tab on the phone and in the web portal (or join the
same workspace in the worker browser). Select that physical glasses device under
Live glasses. Ask or navigate on the glasses: the browser should follow in roughly
one to two seconds on a healthy connection. Background Specs or disconnect: the
viewer must switch to Offline or paused within 12 seconds. Use Browser simulation
to practice independently; its gestures do not control the physical glasses.
