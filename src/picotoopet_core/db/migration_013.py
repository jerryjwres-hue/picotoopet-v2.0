"""Migration 13: durable local ComfyUI production facts."""

MIGRATION_013 = r"""
CREATE TABLE IF NOT EXISTS production_jobs (
    production_job_id        TEXT PRIMARY KEY,
    creative_package_id      TEXT NOT NULL UNIQUE REFERENCES creative_packages(creative_package_id) ON DELETE RESTRICT,
    creative_package_digest  TEXT NOT NULL,
    project_key              TEXT NOT NULL,
    production_profile       TEXT NOT NULL,
    plan_digest              TEXT,
    plan_json                TEXT,
    status                   TEXT NOT NULL,
    lease_executor_id        TEXT,
    lease_token_digest       TEXT,
    lease_expires_at         TEXT,
    failure_code             TEXT,
    error_message            TEXT,
    idempotency_key          TEXT NOT NULL UNIQUE,
    created_at               TEXT NOT NULL,
    updated_at               TEXT NOT NULL,
    finished_at              TEXT
);
CREATE INDEX IF NOT EXISTS idx_production_jobs_status_created
    ON production_jobs(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_production_jobs_project_created
    ON production_jobs(project_key, created_at DESC);

CREATE TABLE IF NOT EXISTS production_tasks (
    production_task_id       TEXT PRIMARY KEY,
    production_job_id        TEXT NOT NULL REFERENCES production_jobs(production_job_id) ON DELETE RESTRICT,
    shot_id                  TEXT NOT NULL,
    order_index              INTEGER NOT NULL,
    render_intent            TEXT NOT NULL,
    execution_disposition    TEXT NOT NULL,
    workflow_id              TEXT,
    task_plan_json           TEXT NOT NULL,
    status                   TEXT NOT NULL,
    attempt_count            INTEGER NOT NULL DEFAULT 0,
    comfy_prompt_id          TEXT,
    output_relpath           TEXT,
    output_sha256            TEXT,
    output_bytes             INTEGER,
    output_mime_type         TEXT,
    output_width             INTEGER,
    output_height            INTEGER,
    output_frame_count       INTEGER,
    output_fps               INTEGER,
    failure_code             TEXT,
    error_message            TEXT,
    created_at               TEXT NOT NULL,
    updated_at               TEXT NOT NULL,
    finished_at              TEXT,
    UNIQUE(production_job_id, shot_id),
    UNIQUE(production_job_id, order_index)
);
CREATE INDEX IF NOT EXISTS idx_production_tasks_job_order
    ON production_tasks(production_job_id, order_index);
CREATE INDEX IF NOT EXISTS idx_production_tasks_status
    ON production_tasks(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS production_attempts (
    production_attempt_id    TEXT PRIMARY KEY,
    production_job_id        TEXT NOT NULL REFERENCES production_jobs(production_job_id) ON DELETE RESTRICT,
    production_task_id       TEXT NOT NULL REFERENCES production_tasks(production_task_id) ON DELETE RESTRICT,
    attempt_number           INTEGER NOT NULL,
    executor_id              TEXT NOT NULL,
    comfy_prompt_id          TEXT,
    status                   TEXT NOT NULL,
    started_at               TEXT NOT NULL,
    finished_at              TEXT,
    failure_code             TEXT,
    error_message            TEXT,
    UNIQUE(production_task_id, attempt_number)
);
CREATE INDEX IF NOT EXISTS idx_production_attempts_task
    ON production_attempts(production_task_id, attempt_number);

CREATE TABLE IF NOT EXISTS production_packages (
    production_package_id    TEXT PRIMARY KEY,
    production_job_id        TEXT NOT NULL UNIQUE REFERENCES production_jobs(production_job_id) ON DELETE RESTRICT,
    creative_package_id      TEXT NOT NULL,
    plan_digest              TEXT NOT NULL,
    package_digest           TEXT NOT NULL UNIQUE,
    package_relpath          TEXT NOT NULL,
    manifest_json            TEXT NOT NULL,
    quality_outcome          TEXT NOT NULL,
    created_at               TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_production_packages_created
    ON production_packages(created_at DESC);
"""
