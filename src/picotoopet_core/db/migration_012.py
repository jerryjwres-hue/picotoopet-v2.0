"""Migration 12: durable Creative Intelligence facts."""

MIGRATION_012 = r"""
CREATE TABLE IF NOT EXISTS creative_jobs (
    creative_job_id          TEXT PRIMARY KEY,
    project_key              TEXT NOT NULL,
    creative_profile         TEXT NOT NULL,
    creative_objective       TEXT,
    objective_digest         TEXT NOT NULL,
    source_set_digest        TEXT NOT NULL,
    status                   TEXT NOT NULL,
    current_stage            TEXT,
    creative_package_id      TEXT,
    deep_ai_handoff_id       TEXT,
    failure_code             TEXT,
    error_message            TEXT,
    idempotency_key          TEXT NOT NULL UNIQUE,
    created_at               TEXT NOT NULL,
    updated_at               TEXT NOT NULL,
    finished_at              TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_creative_jobs_source_identity
    ON creative_jobs(source_set_digest, objective_digest, creative_profile);
CREATE INDEX IF NOT EXISTS idx_creative_jobs_status_created
    ON creative_jobs(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_creative_jobs_project_created
    ON creative_jobs(project_key, created_at DESC);

CREATE TABLE IF NOT EXISTS creative_job_sources (
    creative_job_id          TEXT NOT NULL REFERENCES creative_jobs(creative_job_id) ON DELETE RESTRICT,
    result_package_id        TEXT NOT NULL REFERENCES business_result_packages(result_package_id) ON DELETE RESTRICT,
    result_digest            TEXT NOT NULL,
    source_work_package_id   TEXT NOT NULL REFERENCES business_work_packages(work_package_id) ON DELETE RESTRICT,
    project_key              TEXT NOT NULL,
    created_at               TEXT NOT NULL,
    PRIMARY KEY(creative_job_id, result_package_id)
);
CREATE INDEX IF NOT EXISTS idx_creative_job_sources_result
    ON creative_job_sources(result_package_id);

CREATE TABLE IF NOT EXISTS creative_source_findings (
    creative_job_id          TEXT NOT NULL REFERENCES creative_jobs(creative_job_id) ON DELETE RESTRICT,
    source_finding_ref       TEXT NOT NULL,
    result_package_id        TEXT NOT NULL,
    finding_rank             INTEGER NOT NULL,
    finding_digest           TEXT NOT NULL,
    finding_json             TEXT NOT NULL,
    evidence_ids_json        TEXT NOT NULL,
    created_at               TEXT NOT NULL,
    PRIMARY KEY(creative_job_id, source_finding_ref),
    UNIQUE(creative_job_id, result_package_id, finding_rank)
);
CREATE INDEX IF NOT EXISTS idx_creative_findings_result
    ON creative_source_findings(result_package_id, finding_rank);

CREATE TABLE IF NOT EXISTS creative_stage_runs (
    stage_run_id             TEXT PRIMARY KEY,
    creative_job_id          TEXT NOT NULL REFERENCES creative_jobs(creative_job_id) ON DELETE RESTRICT,
    stage_kind               TEXT NOT NULL,
    status                   TEXT NOT NULL,
    input_digest             TEXT NOT NULL,
    result_digest            TEXT,
    result_json              TEXT,
    model_attempts           INTEGER NOT NULL DEFAULT 0,
    quality_outcome          TEXT,
    failure_code             TEXT,
    error_message            TEXT,
    template_version         TEXT NOT NULL,
    created_at               TEXT NOT NULL,
    updated_at               TEXT NOT NULL,
    finished_at              TEXT,
    UNIQUE(creative_job_id, stage_kind)
);
CREATE INDEX IF NOT EXISTS idx_creative_stage_runs_job
    ON creative_stage_runs(creative_job_id, created_at);

CREATE TABLE IF NOT EXISTS creative_packages (
    creative_package_id      TEXT PRIMARY KEY,
    creative_job_id          TEXT NOT NULL UNIQUE REFERENCES creative_jobs(creative_job_id) ON DELETE RESTRICT,
    source_set_digest        TEXT NOT NULL,
    package_digest           TEXT NOT NULL UNIQUE,
    package_relpath          TEXT NOT NULL,
    manifest_json            TEXT NOT NULL,
    quality_outcome          TEXT NOT NULL,
    created_at               TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_creative_packages_created
    ON creative_packages(created_at DESC);

CREATE TABLE IF NOT EXISTS creative_deep_ai_handoffs (
    handoff_id               TEXT PRIMARY KEY,
    creative_job_id          TEXT NOT NULL UNIQUE REFERENCES creative_jobs(creative_job_id) ON DELETE RESTRICT,
    stage_kind               TEXT NOT NULL,
    source_set_digest        TEXT NOT NULL,
    failed_result_digest     TEXT NOT NULL,
    quality_reasons_json     TEXT NOT NULL,
    return_schema_json       TEXT NOT NULL,
    package_digest           TEXT NOT NULL UNIQUE,
    package_relpath          TEXT NOT NULL,
    status                   TEXT NOT NULL,
    created_at               TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_creative_handoffs_status_created
    ON creative_deep_ai_handoffs(status, created_at DESC);
"""
