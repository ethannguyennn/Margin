# Deploy: relay + Caddy on Vultr, behind `getyourassto.work`

Deploy the mock relay first (`MOCK_MODE=1`), then flip to real mode once Parts 4
and 5 are merged. The public HTTPS origin is the fallback for venue Wi-Fi that
isolates clients; a phone hotspot is the backup.

## 1. VM (once)

1. Vultr: Cloud Compute, Ubuntu 24.04 LTS, 1 vCPU / 1-2 GB is enough. Note the IPv4.
2. Firewall: allow inbound TCP 22, 80, 443 and UDP 443 (HTTP/3).
3. On the VM:
   ```bash
   curl -fsSL https://get.docker.com | sh
   apt-get install -y make git
   git clone -b part-3-relay-infra https://github.com/ethannguyennn/Margin.git margin
   cd margin && cp .env.example .env && nano .env
   ```

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
MARGIN_DOMAIN=getyourassto.work
ACME_EMAIL=<you@...>
PUBLIC_ORIGIN=https://getyourassto.work
ALLOWED_ORIGINS=<origins the WebView sends; see step 5>
SENTRY_DSN_RELAY=<relay project DSN>
SENTRY_ENVIRONMENT=demo
```

Real mode adds `MOCK_MODE=0`, `GEMINI_API_KEY`, the three `GEMINI_MODEL_*`,
`DATABASE_URL`, and the `NOT_FOUND_MIN_*` thresholds from Part 4.

## 4. Run

```bash
make deploy          # build + start relay and caddy, print status
make logs            # follow relay logs
curl -s https://getyourassto.work/v1/health
```

From a phone **on cellular** (Wi-Fi off), open `https://getyourassto.work/v1/health`;
expect `{"ok":true,"mock":true,"db":"mock",...}`.

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
