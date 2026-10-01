CREATE TABLE IF NOT EXISTS roadmap_topic_progress (
    owner_hash char(64) NOT NULL,
    roadmap_id varchar(100) NOT NULL,
    topic_id char(16) NOT NULL,
    completed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (owner_hash, roadmap_id, topic_id)
);
