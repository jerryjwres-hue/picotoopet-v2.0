"""Migration 15: durable paid-AI escalation and quality-learning facts."""

MIGRATION_015 = r"""
CREATE TABLE IF NOT EXISTS deep_ai_escalation_jobs (
    escalation_job_id           TEXT PRIMARY KEY,
    source_kind                 TEXT NOT NULL,
    source_id                   TEXT NOT NULL,
    source_digest               TEXT NOT NULL,
    policy_version              TEXT NOT NULL,
    sanitized_package_relpath   TEXT NOT NULL,
    sanitized_package_digest    TEXT NOT NULL,
    sanitizer_version           TEXT NOT NULL,
    provider_profile_id         TEXT NOT NULL,
    provider_profile_digest     TEXT NOT NULL,
    model_id                    TEXT NOT NULL,
    max_input_tokens            INTEGER NOT NULL,
    max_output_tokens           INTEGER NOT NULL,
    max_calls                   INTEGER NOT NULL,
    max_cost_usd                TEXT NOT NULL,
    status                      TEXT NOT NULL,
    approval_id                 TEXT,
    approval_digest             TEXT,
    approval_expires_at         TEXT,
    validation_outcome          TEXT,
    accepted_result_digest      TEXT,
    accepted_result_relpath     TEXT,
    failure_code                TEXT,
    error_message               TEXT,
    created_at                  TEXT NOT NULL,
    updated_at                  TEXT NOT NULL,
    finished_at                 TEXT,
    UNIQUE(source_kind, source_id, source_digest, policy_version),
    CHECK(max_input_tokens >= 0),
    CHECK(max_output_tokens >= 0),
    CHECK(max_calls >= 1 AND max_calls <= 2)
);
CREATE INDEX IF NOT EXISTS idx_deep_ai_jobs_status_created
    ON deep_ai_escalation_jobs(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_deep_ai_jobs_source
    ON deep_ai_escalation_jobs(source_kind, source_id);

CREATE TABLE IF NOT EXISTS deep_ai_attempts (
    attempt_id                  TEXT PRIMARY KEY,
    escalation_job_id           TEXT NOT NULL REFERENCES deep_ai_escalation_jobs(escalation_job_id) ON DELETE RESTRICT,
    attempt_number              INTEGER NOT NULL,
    status                      TEXT NOT NULL,
    estimated_cost_usd          TEXT NOT NULL,
    provider_request_id         TEXT,
    response_digest             TEXT,
    response_relpath            TEXT,
    input_tokens                INTEGER,
    output_tokens               INTEGER,
    actual_cost_usd             TEXT,
    cost_source                 TEXT,
    created_at                  TEXT NOT NULL,
    updated_at                  TEXT NOT NULL,
    completed_at                TEXT,
    UNIQUE(escalation_job_id, attempt_number),
    CHECK(attempt_number >= 1 AND attempt_number <= 2),
    CHECK(input_tokens IS NULL OR input_tokens >= 0),
    CHECK(output_tokens IS NULL OR output_tokens >= 0)
);
CREATE INDEX IF NOT EXISTS idx_deep_ai_attempts_job_number
    ON deep_ai_attempts(escalation_job_id, attempt_number);

CREATE TABLE IF NOT EXISTS deep_ai_learning_events (
    event_id                    TEXT PRIMARY KEY,
    idempotency_key             TEXT NOT NULL UNIQUE,
    project_key                 TEXT NOT NULL,
    source_kind                 TEXT NOT NULL,
    source_id                   TEXT NOT NULL,
    local_quality_outcome       TEXT NOT NULL,
    escalation_job_id           TEXT REFERENCES deep_ai_escalation_jobs(escalation_job_id) ON DELETE RESTRICT,
    human_action                TEXT NOT NULL,
    reason_tags_json            TEXT NOT NULL,
    final_content_digest        TEXT,
    created_at                  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_deep_ai_learning_project_created
    ON deep_ai_learning_events(project_key, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_deep_ai_learning_source
    ON deep_ai_learning_events(source_kind, source_id, created_at DESC);
"""
