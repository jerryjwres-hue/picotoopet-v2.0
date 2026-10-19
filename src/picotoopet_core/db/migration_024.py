"""Schema 24: immutable Goal synthesis source snapshots for canonical Creative jobs."""

MIGRATION_024 = r"""
CREATE TABLE IF NOT EXISTS creative_goal_source_sets (
    creative_job_id          TEXT PRIMARY KEY REFERENCES creative_jobs(creative_job_id) ON DELETE RESTRICT,
    goal_id                  TEXT NOT NULL UNIQUE REFERENCES autonomous_goals(goal_id) ON DELETE RESTRICT,
    discovery_result_hash    TEXT NOT NULL,
    synthesis_result_hash    TEXT NOT NULL,
    source_set_digest        TEXT NOT NULL,
    source_set_json          TEXT NOT NULL,
    created_at               TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_creative_goal_sources_goal ON creative_goal_source_sets(goal_id);
"""
