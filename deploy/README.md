# Deploy: relay + Caddy on Vultr, behind `getyourassto.work`

Deploy the mock relay first (`MOCK_MODE=1`), then flip to real mode once Parts 4
and 5 are merged. The public HTTPS origin is the fallback for venue Wi-Fi that
isolates clients; a phone hotspot is the backup.

v2: one origin serves both the API (`https://getyourassto.work/v1/...`) and the
employer portal (`https://getyourassto.work/portal/`). `deploy/caddy.Dockerfile`
builds Part 5's `portal/` (base `/portal/`) into the Caddy image; while `portal/`
is not on the deployed branch it serves a placeholder page. The portal is same
origin, so it needs no CORS entry.

## 1. VM (once)

1. Vultr: Cloud Compute, Ubuntu 24.04 LTS, 1 vCPU / 1-2 GB is enough. Note the IPv4.
2. Firewall: allow inbound TCP 22, 80, 443 and UDP 443 (HTTP/3).
3. On the VM:
   ```bash
   curl -fsSL https://get.docker.com | sh
   apt-get install -y make git
   git clone -b main https://github.com/ethannguyennn/Specs.git specs
   cd specs && cp .env.example .env && nano .env
   ```

### Moving a VM from the Margin name to Specs (once)

The project was renamed from Margin. A VM set up before the rename still has a
`~/margin` checkout, a `MARGIN_DOMAIN` line in `.env` and a running compose
project named `margin`, which holds ports 80/443. Before the first deploy after
the rename:

```bash
cd ~/margin && docker compose -p margin -f deploy/docker-compose.yml down
cd ~ && mv margin specs && cd specs
git remote set-url origin https://github.com/ethannguyennn/Specs.git
git pull --ff-only
sed -i 's/^MARGIN_/SPECS_/' .env
make deploy
```

The new `specs` project starts with empty `caddy_data`, so Caddy requests fresh
certificates on the first start (one issuance per host; well inside Let's
Encrypt limits). The database is external, so no data moves.

## 2. DNS (Porkbun)

The relay is served at the root domain. Porkbun -> Domain Management ->
getyourassto.work -> DNS:

1. Delete the default parking records pointing at `pixie.porkbun.com` (the root
   **ALIAS** and the `*` **CNAME**).
2. Add: type **A**, host **(blank)**, answer **45.32.88.132**, TTL 600.

Check with `nslookup getyourassto.work` (must return only 45.32.88.132) before
starting Caddy, or the Let's Encrypt challenge fails (and rate-limits retries).

## 3. `.env` on the VM (minimum for the mock relay)

```
MOCK_MODE=1
SPECS_DOMAIN=getyourassto.work
ACME_EMAIL=<you@...>
PUBLIC_ORIGIN=https://getyourassto.work
ALLOWED_ORIGINS=<origins the WebView sends; see step 5>
SENTRY_DSN_RELAY=<relay project DSN>
SENTRY_ENVIRONMENT=demo
```

Real mode adds `MOCK_MODE=0`, `GEMINI_API_KEY`, the `GEMINI_MODEL_*` IDs,
`DATABASE_URL`, and the `NOT_FOUND_MIN_*` thresholds from Part 4.

v2 adds:

```
PORTAL_TOKEN=<long random string; typed into the portal login, never bundled>
GEMINI_MODEL_CONVERT=<Part 4's conversion model, e.g. gemini-3.8-flash>
MAX_UPLOAD_MB=20          # Caddy also caps request bodies at 22 MB
CONVERT_TIMEOUT_S=180
```

`SPECS_DOMAIN` may list several hosts while switching, e.g.
`SPECS_DOMAIN=getyourassto.work, 45-32-88-132.sslip.io`; Caddy gets a
certificate for each. Apply a `.env` change with `make deploy` (or, for Caddy
only, `docker compose -f deploy/docker-compose.yml --env-file .env up -d caddy`).

Portal auth is one shared supervisor token (`PORTAL_TOKEN`) for one organisation.
Per-supervisor accounts and SSO are v3. Uploaded files are stored, so "synthetic
material only" is enforced by people (the portal says so on every page), not code.

## 4. Run

```bash
make deploy          # build + start relay and caddy, print status
make logs            # follow relay logs
curl -s https://getyourassto.work/v1/health
```

From a phone **on cellular** (Wi-Fi off), open `https://getyourassto.work/v1/health`;
expect `{"ok":true,"mock":true,"db":"mock",...}`. Then open
`https://getyourassto.work/portal/` and log in with `PORTAL_TOKEN`.

Restarts: `restart: unless-stopped` brings back a relay that exits; the
healthcheck SIGTERMs a relay that stops answering (after a 60 s boot grace) so
the same policy restarts it.

## 5. Verify the real device origin (do not guess it)

Run the app on the glasses against the relay, press once, then
`make logs | grep "CORS rejected origin"`. Put that exact origin into
`ALLOWED_ORIGINS` (comma-separated), `make deploy`, retry: the preflight must
now be 2xx. The simulator / Vite dev origin is `http://localhost:5174`.

## 6. Hand Part 1 the whitelist string

`app/app.json` network permission whitelist entry must be exactly
`https://getyourassto.work` (full origin, no wildcard, no path, no trailing slash),
and `VITE_RELAY_ORIGIN` must be the same string.

## Local hardware sideload

`make dev-relay` binds `0.0.0.0:8080`; point the app at `http://<laptop LAN IP>:8080`
(never `localhost` on the phone) and allow that origin via `ALLOWED_ORIGINS` or
`ALLOWED_ORIGIN_REGEX`.

## SOP upload library deployment and verification

The upload-library change is on `codex/sop-cloud-persistence`. On the VM, after
checking that the checkout has no uncommitted work:

```bash
cd /root/specs
git status --short
git fetch origin codex/sop-cloud-persistence
git switch codex/sop-cloud-persistence
make deploy
```

Use `MOCK_MODE=0`, a working `DATABASE_URL`, `PORTAL_TOKEN`, and
`GEMINI_MODEL_CONVERT` in the VM's existing `.env`. Do not copy database or
provider credentials into the portal. The current database schema already
stores uploads; this change adds no migration or storage service.

Open `/portal/`, log in, upload a synthetic SOP, and choose **Library**. Its
source file is saved before the upload receives 202. Search by ID/title/file,
download the original, and confirm it remains listed after a reload or a new
login. Conversion failure does not delete the original. Review and approval
are still required to publish the procedure for workers and Q&A.

Read-only HTTPS verification from the VM, using the container's token without
printing it (requires at least one upload; verifies the newest file):

```bash
docker compose -f deploy/docker-compose.yml --env-file .env exec -T relay python - <<'PY'
import hashlib
import httpx
from specs_relay.config import Settings
s = Settings()
assert s.portal_token, 'PORTAL_TOKEN must be configured'
headers = {'Authorization': 'Bearer ' + s.portal_token.get_secret_value()}
with httpx.Client(base_url=s.public_origin, headers=headers, timeout=30) as client:
    health = client.get('/v1/health'); health.raise_for_status()
    assert health.json()['db'] == 'ok' and not health.json()['mock']
    library = client.get('/v1/materials?limit=1'); library.raise_for_status()
    assert library.json()['items'], 'Upload a synthetic SOP first'
    item = library.json()['items'][0]
with httpx.Client(base_url=s.public_origin, headers=headers, timeout=30) as client:
    original = client.get('/v1/materials/' + item['material_id'] + '/file')
    original.raise_for_status()
    assert len(original.content) == item['size_bytes']
    assert hashlib.sha256(original.content).hexdigest() == item['sha256']
print('PASS: original SOP is listed and byte-exact over HTTPS in a fresh session')
PY
```

This command reads existing data only. For the separately opt-in database
restart/reconnection test and cleanup behavior, see `portal/README.md`.

## TODO audit configuration (2026-10-18)

`codex/todo-audit-completion` includes the SOP library and current `main`, plus
source-based walkthrough citations, offline phone mocks and the Sentry tunnel.
The public relay answers version 0.3.0 and root-domain CORS now passes, but this
machine cannot authenticate over SSH to confirm/deploy its exact revision.

Deploy that branch with the same fetch/switch/`make deploy` workflow above.
Keep the existing VM `.env` private. Confirm `PUBLIC_ORIGIN` is the root HTTPS
origin; keep the already working root-domain CORS entry and add the actual lens
origin only after observing it from a device. The local audited app pack uses
`VITE_RELAY_ORIGIN=https://getyourassto.work`, `VITE_MOCK=0`.

For the coffee bank, `eval/results/2026-10-18-gate-calibration.json` records the
candidate thresholds (`0.7389722026007067`, `0.031754032258064516`), already
applied to the local private env. They protect all answerable and clarification
questions in the development bank. Recalibrate for a new bank/model rather than
treating those as universal defaults. Provider quota still blocks sustained
live QA on `gemini-3.5-flash-lite`; no billing/account settings were changed.

For the telemetry tunnel, configure server `SENTRY_DSN_APP` to **exactly** the
app build's public `VITE_SENTRY_DSN`, then opt in with `VITE_SENTRY_TUNNEL=1`.
The tunnel defaults off when the app DSN is absent. It accepts only that DSN,
caps streamed envelopes at 256 KB, rate limits each client to 60/min and never
follows upstream redirects. Its tests mock the upstream: physical trace
collection and confirmation in Sentry remain open hardware/integration checks.
