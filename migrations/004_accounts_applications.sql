CREATE TABLE IF NOT EXISTS user_accounts (
    id uuid PRIMARY KEY,
    email varchar(254) NOT NULL UNIQUE,
    password_hash text NOT NULL,
    owner_hash char(64) NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS user_sessions (
    token_hash char(64) PRIMARY KEY,
    account_id uuid NOT NULL REFERENCES user_accounts(id) ON DELETE CASCADE,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS user_sessions_account_idx ON user_sessions (account_id);

ALTER TABLE job_applications ADD COLUMN IF NOT EXISTS status varchar(24) NOT NULL DEFAULT 'applied';
ALTER TABLE job_applications ADD COLUMN IF NOT EXISTS follow_up_on date;
ALTER TABLE job_applications ADD COLUMN IF NOT EXISTS contact_name varchar(160) NOT NULL DEFAULT '';
ALTER TABLE job_applications ADD COLUMN IF NOT EXISTS contact_email varchar(254) NOT NULL DEFAULT '';
ALTER TABLE job_applications ADD COLUMN IF NOT EXISTS resume_version_id uuid;
ALTER TABLE job_applications ADD COLUMN IF NOT EXISTS job_description text NOT NULL DEFAULT '';
ALTER TABLE job_applications ADD COLUMN IF NOT EXISTS cover_letter text NOT NULL DEFAULT '';
ALTER TABLE job_applications ADD COLUMN IF NOT EXISTS recruiter_message text NOT NULL DEFAULT '';
ALTER TABLE job_applications ADD COLUMN IF NOT EXISTS interview_prep text NOT NULL DEFAULT '';
ALTER TABLE job_applications ADD CONSTRAINT job_applications_status_check
    CHECK (status IN ('saved', 'applying', 'applied', 'interviewing', 'offer', 'accepted', 'rejected', 'withdrawn'));
CREATE INDEX IF NOT EXISTS job_applications_owner_follow_up_idx
    ON job_applications (owner_hash, follow_up_on) WHERE follow_up_on IS NOT NULL;
