# Specs employer portal

Vite and vanilla TypeScript. Production output is `portal/dist`, with a
`/portal/` base. API calls always use the same origin at `/v1/`. Enter the shared
portal token at login; it stays in sessionStorage and is sent as a Bearer header,
including when loading diagram previews. No token is compiled into the bundle.

## Saved SOP uploads

Choose **Library** to search uploaded SOPs by document ID, title or filename.
The library is loaded from the relay/database, so it works in a new browser
session after logging in; it does not depend on the last draft in sessionStorage.
Each upload includes its conversion status and an authenticated **Download
original** action. A failed or interrupted conversion keeps its original file.
The source download sends the portal token in a header, never a link/query string.

`POST /v1/materials` commits the source file and metadata to Postgres before
returning 202. `GET /v1/materials?q=...&limit=25&offset=0` returns metadata
with `next_offset`; `GET /v1/materials/{id}/file` returns the stored bytes as an
attachment. Both retrieval endpoints require the portal token. In real mode,
unavailable persistent storage returns 503 instead of accepting a mock upload.
Explicit `MOCK_MODE=1` remains an in-memory demonstration, not durable storage.

Files up to 20 MB live in the existing `materials.bytes` column in the configured
cloud Postgres database, not the web server's filesystem. No additional object
storage service or migration is needed. Conversion, verification and supervisor
approval remain required before an upload appears in published procedures/Q&A.

Opt-in cloud persistence check from the repository root (uses `.env` DATABASE_URL):

```powershell
$env:PYTHONPATH = 'relay/src'
$env:SPECS_TEST_UPLOAD_DATABASE = '1'
.venv/Scripts/python.exe -m pytest relay/tests/test_material_library_live.py -q
```

This checks the real database through the local HTTP API with deterministic
conversion, recreates the relay/reconnects Postgres, verifies byte-exact retrieval,
and deletes only its randomly named synthetic test records. It is not a deployed
HTTPS test or a live Gemini conversion test. Keep database/API credentials on
the relay; never copy them into Vite environment variables.

## Run

From the repository root:

```powershell
npm --prefix portal ci
npm --prefix portal run dev       # http://127.0.0.1:5178/portal/
npm --prefix portal test
npm --prefix portal run build
```

The development server proxies `/v1/` to the relay on `127.0.0.1:8080`.
Production Caddy/static deployment and Makefile wiring belong to Part 3.
No new relay dependency or environment variable is required by Part 5.

Review highlights quotes in the source text, provides editable glance/body/
warning/checkpoint fields with counts and save-time verification, imports the
app's `renderScreen` for the lens preview, and displays authenticated diagram
PNGs. Publish stays disabled while any step fails, any attached diagram is
unapproved, or edits are unsaved. Published revisions are read-only. Devices,
assignment and the 3-second progress board complete the employer flow.

The new authoring JSON stays opaque at the API boundary rather than declaring
competing copies of Part 3's models. Shared lens types and rendering come from
`app/`; all Python data models come from `schemas.py`. This checkout's shared
renderer still draws the v1 WALKTHROUGH screen; the actual v2 renderer must come
from Part 1. No replacement renderer lives in the portal.

## Explicit local fixture API

Part 3's v2 mock relay was not published during implementation. These checks
use an independently labeled fixture API, not a replacement relay:

```powershell
npm --prefix portal run dev:fixture   # http://127.0.0.1:5177/portal/
# Log in with the public test credential: fixture-token
# In a second shell, from the repository root:
& portal/tests/browser-smoke.ps1
```

The smoke script uses the installed gstack `/browse` tool and runs upload,
failed verification, correction, diagram approval, publication, pairing,
assignment and a board update. Screenshots and a trace are in `tests/evidence/`.
The diagram is synthetic test artwork, not Part 4 renderer output. The fixture
server/config is excluded from the production entry point. The `__fixture/next`
route exists only in this test server.

`npm test` uses jsdom and a fetch fixture. It covers the same workflow, 409
reasons, session auth, quote escaping, approval gates, shared lens rendering,
character counts, polling and cancellation. These checks cannot prove upload
parsing, authorization or conversion correctness in Part 3's relay.

See `../docs/handoffs/PART-5.md` for database commands, integration requests,
actual test results and the deferred real-system gates.
