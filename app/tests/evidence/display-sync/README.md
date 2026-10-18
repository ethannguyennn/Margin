# Display feed evidence — synthetic publishers only

2026-10-18, Windows. Both web apps received the same live STEP and two-tile DIAGRAM
updates via `/v1/lens/display` and the authenticated workspace viewer routes.
The local relay ran MOCK_MODE=1 with settings isolated from live keys and DB.
The source was explicitly named `SYNTHETIC G2 publisher`; it was an HTTP fixture,
not a physical G2 or a screen capture from the official simulator.

- `worker-diagram-mock.png`: worker dark theme, shared two-tile feed.
- `portal-diagram-mock.png`: portal light theme, the same feed.
- `worker-offline-mock.png`: publisher paused, stale/offline status.

Both browsers joined the synthetic workspace using the normal UI. Changing the
fixture from STEP to DIAGRAM updated both without browser interaction. Marking
the publisher disconnected changed the status to Offline or paused. The fixed
worker navigation overlays the bottom of the page at this scroll position; the
display and footer remain reachable by scrolling.

Tests cover ack gating, coalescing, heartbeat/pause, serialized sends, restart,
superseded streams, abort on disposal, stale viewing, selection races, reference
image fallback, auth, workspace moves/isolation, payload bounds and diagram tiles.
Physical glasses were unavailable; hardware testing remains pending.
