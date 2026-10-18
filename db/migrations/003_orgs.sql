-- Workspaces: an admin's join code links glasses to that admin's SOPs. Safe to apply repeatedly.
CREATE TABLE IF NOT EXISTS orgs (
    org_id text PRIMARY KEY,
    name text NOT NULL,
    join_code text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE SEQUENCE IF NOT EXISTS org_id_seq;
-- Everything that existed before workspaces (the seeded demo bank) is the demo workspace.
INSERT INTO orgs (org_id, name, join_code) VALUES ('default', 'Demo workspace', 'DEMO')
    ON CONFLICT DO NOTHING;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS org_id text NOT NULL DEFAULT 'default' REFERENCES orgs (org_id);
ALTER TABLE materials ADD COLUMN IF NOT EXISTS org_id text NOT NULL DEFAULT 'default' REFERENCES orgs (org_id);
ALTER TABLE devices ADD COLUMN IF NOT EXISTS org_id text REFERENCES orgs (org_id);
CREATE INDEX IF NOT EXISTS documents_org_idx ON documents (org_id, status);
