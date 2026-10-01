CREATE TABLE IF NOT EXISTS schema_migrations (
    version integer PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS saved_versions (
    id uuid PRIMARY KEY,
    owner_hash char(64) NOT NULL,
    created_at timestamptz NOT NULL,
    label varchar(100) NOT NULL,
    job_description text NOT NULL DEFAULT '',
    percentage smallint NOT NULL CHECK (percentage BETWEEN 0 AND 100),
    analysis jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS saved_versions_owner_date_idx
    ON saved_versions (owner_hash, created_at DESC);

CREATE TABLE IF NOT EXISTS roadmap_progress (
    owner_hash char(64) NOT NULL,
    roadmap_id varchar(100) NOT NULL,
    status varchar(16) NOT NULL CHECK (status IN ('saved', 'studying', 'completed')),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (owner_hash, roadmap_id)
);
