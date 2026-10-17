-- Run through margin_relay.db.apply_migrations: EMBED_DIM is validated and rendered.
-- Deliberately no dimension default here: config is the single source of truth.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS documents (
    doc_id text NOT NULL,
    revision text NOT NULL,
    title text NOT NULL,
    status text NOT NULL CHECK (status IN ('effective', 'superseded', 'draft')),
    effective_date date,
    PRIMARY KEY (doc_id, revision)
);
CREATE UNIQUE INDEX IF NOT EXISTS documents_one_effective_idx
    ON documents (doc_id) WHERE status = 'effective';

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id text PRIMARY KEY,
    doc_id text NOT NULL,
    revision text NOT NULL,
    section text NOT NULL,
    is_step boolean NOT NULL DEFAULT false,
    step_order integer,
    heading text,
    text text NOT NULL,
    tsv tsvector GENERATED ALWAYS AS (
        to_tsvector('english', coalesce(heading, '') || ' ' || text)
    ) STORED,
    embedding vector({{EMBED_DIM}}) NOT NULL,
    FOREIGN KEY (doc_id, revision) REFERENCES documents (doc_id, revision),
    CHECK (chunk_id = doc_id || ':' || revision || ':' || section),
    CHECK ((is_step AND step_order > 0 AND step_order IS NOT NULL)
        OR (NOT is_step AND step_order IS NULL))
);
CREATE INDEX IF NOT EXISTS chunks_tsv_idx ON chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS chunks_vec_idx ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_doc_idx ON chunks (doc_id, revision, step_order);
CREATE UNIQUE INDEX IF NOT EXISTS chunks_step_order_idx
    ON chunks (doc_id, revision, step_order) WHERE is_step;

CREATE TABLE IF NOT EXISTS sessions (
    session_id uuid PRIMARY KEY,
    started_at timestamptz NOT NULL DEFAULT now(),
    device text,
    app_version text
);

CREATE TABLE IF NOT EXISTS events (
    ts timestamptz NOT NULL DEFAULT now(),
    session_id uuid,
    trace_id text,
    intent text,
    outcome text,
    doc_ids text[],
    transcript text,
    latency_ms jsonb NOT NULL DEFAULT '{}'::jsonb,
    CHECK (jsonb_typeof(latency_ms) = 'object')
);
SELECT create_hypertable('events', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS events_session_ts_idx ON events (session_id, ts DESC);

CREATE SEQUENCE IF NOT EXISTS deviation_id_seq START 1;
CREATE TABLE IF NOT EXISTS deviations (
    deviation_id text PRIMARY KEY,
    ts timestamptz NOT NULL DEFAULT now(),
    session_id uuid,
    doc_id text,
    step_id text,
    text text NOT NULL CHECK (length(btrim(text)) > 0),
    notified boolean NOT NULL DEFAULT false
);
