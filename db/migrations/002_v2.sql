-- Additive v2 authoring, device and progress storage. Safe to apply repeatedly.
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS glance text;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS body text;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS warning text;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS checkpoint text;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS diagram_id text;

CREATE SEQUENCE IF NOT EXISTS material_id_seq;
CREATE SEQUENCE IF NOT EXISTS diagram_id_seq;
CREATE SEQUENCE IF NOT EXISTS device_id_seq;
CREATE SEQUENCE IF NOT EXISTS assignment_id_seq;

CREATE TABLE IF NOT EXISTS materials (
    material_id text PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now(),
    filename text NOT NULL,
    mime text NOT NULL,
    -- ponytail: cap bytea at 20 MB; move files to object storage when uploads grow.
    bytes bytea NOT NULL CHECK (octet_length(bytes) <= 20 * 1024 * 1024),
    sha256 text NOT NULL,
    doc_id text NOT NULL,
    revision text NOT NULL,
    title text NOT NULL,
    status text NOT NULL CHECK (status IN ('converting', 'ready', 'failed', 'approved')),
    error text,
    material_text jsonb
);
CREATE TABLE IF NOT EXISTS drafts (
    doc_id text NOT NULL,
    revision text NOT NULL,
    material_id text NOT NULL REFERENCES materials(material_id),
    title text NOT NULL,
    steps jsonb NOT NULL,
    warnings jsonb NOT NULL DEFAULT '[]',
    updated_at timestamptz NOT NULL DEFAULT now(),
    approved_at timestamptz,
    PRIMARY KEY (doc_id, revision)
);
CREATE TABLE IF NOT EXISTS diagrams (
    diagram_id text PRIMARY KEY,
    doc_id text NOT NULL,
    revision text NOT NULL,
    step_label text NOT NULL,
    spec jsonb NOT NULL,
    tiles bytea[] NOT NULL,
    preview_png bytea NOT NULL CHECK (octet_length(preview_png) <= 20 * 1024 * 1024),
    approved boolean NOT NULL DEFAULT false,
    CHECK (cardinality(tiles) BETWEEN 1 AND 2),
    CHECK (octet_length(tiles[1]) <= 20 * 1024 * 1024),
    CHECK (tiles[2] IS NULL OR octet_length(tiles[2]) <= 20 * 1024 * 1024)
);
CREATE TABLE IF NOT EXISTS devices (
    device_id text PRIMARY KEY,
    token_sha256 text NOT NULL UNIQUE,
    pair_code text,
    pair_expires timestamptz,
    worker_name text,
    claimed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS devices_open_code
    ON devices(pair_code) WHERE claimed_at IS NULL;
CREATE TABLE IF NOT EXISTS assignments (
    assignment_id text PRIMARY KEY,
    device_id text NOT NULL REFERENCES devices(device_id),
    doc_id text NOT NULL,
    revision text NOT NULL,
    assigned_at timestamptz NOT NULL DEFAULT now(),
    delivered_at timestamptz,
    completed_at timestamptz,
    FOREIGN KEY (doc_id, revision) REFERENCES documents(doc_id, revision)
);
CREATE INDEX IF NOT EXISTS assignments_pending
    ON assignments(device_id, assigned_at) WHERE delivered_at IS NULL;
CREATE TABLE IF NOT EXISTS progress (
    ts timestamptz NOT NULL,
    assignment_id text NOT NULL REFERENCES assignments(assignment_id),
    step_id text,
    kind text NOT NULL CHECK (kind IN (
        'task_started', 'step_started', 'step_completed', 'task_paused', 'task_completed')),
    received_at timestamptz NOT NULL DEFAULT now(),
    -- Task events have NULL step_id. Coalesce it in the index below so retries
    -- deduplicate those too, including on PG versions without NULLS NOT DISTINCT.
    CHECK (step_id IS NULL OR step_id <> '')
);
SELECT create_hypertable('progress', 'ts', if_not_exists => TRUE);
-- Timescale requires the time partition column in every unique index.
CREATE UNIQUE INDEX IF NOT EXISTS progress_idempotency
    ON progress(assignment_id, coalesce(step_id, ''), kind, ts);
CREATE INDEX IF NOT EXISTS progress_assignment_ts ON progress(assignment_id, ts DESC);
-- Asks made inside an assigned task carry its id (BUILD-PLAN-V2 §5 AskRequest.context).
ALTER TABLE events ADD COLUMN IF NOT EXISTS assignment_id text;
