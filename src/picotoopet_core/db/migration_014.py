"""Migration 14: durable end-to-end business pipeline and return packages."""

MIGRATION_014 = r"""
CREATE TABLE IF NOT EXISTS business_pipeline_runs (
    pipeline_run_id        TEXT PRIMARY KEY,
    work_package_id        TEXT NOT NULL UNIQUE,
    result_package_id      TEXT UNIQUE,
    creative_job_id        TEXT UNIQUE,
    creative_package_id    TEXT UNIQUE,
    production_job_id      TEXT UNIQUE,
    production_package_id  TEXT UNIQUE,
    return_package_id      TEXT UNIQUE,
    project_key            TEXT NOT NULL,
    producer_id            TEXT NOT NULL,
    producer_version       TEXT NOT NULL,
    adapter_profile        TEXT NOT NULL,
    status                 TEXT NOT NULL,
    quality_outcome        TEXT,
    failure_code           TEXT,
    error_message          TEXT,
    idempotency_key        TEXT NOT NULL UNIQUE,
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL,
    finished_at            TEXT
);
CREATE INDEX IF NOT EXISTS idx_business_pipeline_status_created
    ON business_pipeline_runs(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_business_pipeline_project_created
    ON business_pipeline_runs(project_key, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_business_pipeline_updated
    ON business_pipeline_runs(updated_at DESC);

CREATE TABLE IF NOT EXISTS business_return_packages (
    return_package_id      TEXT PRIMARY KEY,
    pipeline_run_id        TEXT NOT NULL UNIQUE REFERENCES business_pipeline_runs(pipeline_run_id) ON DELETE RESTRICT,
    package_digest         TEXT NOT NULL UNIQUE,
    package_relpath        TEXT NOT NULL,
    manifest_json          TEXT NOT NULL,
    quality_outcome        TEXT NOT NULL,
    created_at             TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_business_return_packages_created
    ON business_return_packages(created_at DESC);
"""
