# Caddy + the employer portal (Part 5's portal/, built with base /portal/), served
# from the same origin as the API so the portal needs no CORS. Build context is the
# repo root (see docker-compose.yml). The portal imports the lens renderer from
# app/src, so the whole context is copied (node_modules/.env are .dockerignored).
FROM node:22-alpine AS portal
WORKDIR /src
COPY . .
RUN if [ -f portal/package.json ]; then \
      cd portal && npm ci --no-audit --no-fund && npm run build; \
    else \
      mkdir -p portal/dist && \
      printf '%s\n' '<!doctype html><meta charset="utf-8"><title>Specs portal</title>' \
        '<p>The portal is not on this branch yet (Part 5 builds portal/).</p>' > portal/dist/index.html; \
    fi

FROM node:22-alpine AS worker
WORKDIR /src
COPY app/package.json app/package-lock.json ./app/
RUN cd app && npm ci --no-audit --no-fund
COPY . .
ARG APP_RELAY_ORIGIN=https://getyourassto.work
RUN cd app && VITE_RELAY_ORIGIN="$APP_RELAY_ORIGIN" VITE_MOCK=0 VITE_ASK_TIMEOUT_MS=50000 npm run build

FROM caddy:2.8
COPY --from=portal /src/portal/dist /srv/portal
COPY --from=worker /src/app/dist /srv/app
COPY deploy/Caddyfile /etc/caddy/Caddyfile
