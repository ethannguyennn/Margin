# Margin relay image. Build context is the repo root (see docker-compose.yml).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CORPUS_DIR=/srv/margin/corpus

WORKDIR /srv/margin

# Dependencies first so code edits do not reinstall them. Editable, so the package
# lives at /srv/margin/relay/src and db.py resolves /srv/margin/db/seed.py and
# /srv/margin/corpus for POST /v1/ingest.
COPY relay/pyproject.toml relay/pyproject.toml
COPY relay/src relay/src
RUN pip install -e ./relay

# Everything else the relay may read at runtime (corpus for /v1/ingest, db/ migrations).
COPY . .
RUN cp deploy/healthcheck.py /usr/local/bin/margin-healthcheck \
 && useradd --system --uid 10001 --no-create-home margin \
 && chown -R margin /srv/margin
USER margin

EXPOSE 8080
# Exec form: uvicorn is PID 1, so the healthcheck's SIGTERM reaches it directly.
CMD ["uvicorn", "margin_relay.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]
