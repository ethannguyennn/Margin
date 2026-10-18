# SOP cloud storage handoff

Branch: `codex/sop-cloud-persistence`, based on the pulled `main` at `ff94e84`.
Validation date: 2026-10-18.

## Behavior

The existing upload endpoint already commits original file bytes, metadata and
SHA-256 to Postgres before returning 202. This change makes those files
discoverable after leaving the conversion screen: **Library** searches the
server's uploads, paginates them, shows ready/approved/converting/failed status,
and downloads the original with portal authentication. A fresh browser login
does not need a previously saved draft ID. The file remains available if
conversion fails or the relay restarts.

New endpoints:

- `GET /v1/materials?q=&limit=25&offset=0`: metadata plus `next_offset`.
- `GET /v1/materials/{id}/file`: byte-exact attachment, `nosniff`, `no-store`.

Both require `PORTAL_TOKEN`. No token appears in a URL or download link. The
library never returns raw file bytes or extracted text. Search uses bound SQL
parameters and literal substring matching. Real-mode upload/list/download cannot
silently use a fallback MockDB; they return 503 if persistent storage is absent.
Explicit `MOCK_MODE=1` continues to be a volatile demonstration.

Uploads get a 120-second browser timeout instead of the generic 15-second API
timeout, allowing the existing 20 MB upload limit on slower connections. The
response includes the saved material's `Location`. There is no automatic retry
that might upload duplicates after an uncertain network failure.

No new service, dependency, schema migration, credential, or automatic publishing
was added. Review/verification/approval still gates worker procedures and Q&A.

## Actual validation

- Relay regression: **689 passed, 13 skipped**, one Starlette/httpx deprecation
  warning. Skipped tests opt in to live providers/databases separately.
- Portal: **9 passed**; TypeScript and production Vite build passed.
- Opt-in cloud persistence test: **1 passed** against the configured real
  Postgres database. An isolated synthetic SOP was uploaded through the HTTP
  API, saved with matching bytes/SHA-256, retrieved after recreating the app and
  reconnecting the database, and remained downloadable after a forced conversion
  failure. The test cleaned up only its own randomly named records. Conversion
  in this test is deterministic, not a Gemini result. It does not use the
  deployed HTTPS endpoint or restart the live VM.
- Browser inspection: local labeled fixture library rendered with source
  metadata and download/open actions. Screenshot:
  `portal/tests/evidence/sop-library-fixture.png`. This is local fixture evidence.
- Deployed `/v1/health` was read: `ok=true`, `mock=false`, `db=ok`.
  New endpoints have **not** been deployed or tested over public HTTPS here.

Reproduction from the repository root (Windows PowerShell):

```powershell
$env:PYTHONPATH = 'relay/src'
.venv/Scripts/python.exe -m pytest relay/tests -q
npm.cmd --prefix portal test
npm.cmd --prefix portal run build

# Opt in separately; uses the existing private .env DATABASE_URL.
$env:SPECS_TEST_UPLOAD_DATABASE = '1'
.venv/Scripts/python.exe -m pytest relay/tests/test_material_library_live.py -q
```

## Deployment status

SSH to `root@45.32.88.132` reached the VM but authentication was rejected. This
Windows account has no default SSH key or running SSH agent. The local `.env`
contains no SSH/private-key material or key-file reference. No VM code,
configuration, containers, or production records were changed.

Once the authorized `margin-deploy@enguy-laptop` key is available to the deploying
computer, use the branch deployment and read-only HTTPS verification commands in
`deploy/README.md` under **SOP upload library deployment and verification**.
They read `PORTAL_TOKEN` inside the relay container without exposing it. Preserve
the VM's `.env`; its credentials are separate from the portal's public bundle.
