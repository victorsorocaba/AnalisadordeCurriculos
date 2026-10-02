CREATE TABLE IF NOT EXISTS job_applications (
    id uuid PRIMARY KEY,
    owner_hash char(64) NOT NULL,
    company varchar(160) NOT NULL,
    role varchar(160) NOT NULL,
    source varchar(120) NOT NULL,
    vacancy_url text NOT NULL DEFAULT '',
    applied_on date NOT NULL,
    response_received boolean NOT NULL DEFAULT false,
    notes text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS job_applications_owner_date_idx
    ON job_applications (owner_hash, applied_on DESC, created_at DESC);
