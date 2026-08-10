"""Migration 11: durable business automation and local-intelligence facts."""

MIGRATION_011 = r"""
CREATE TABLE IF NOT EXISTS business_work_packages (
    work_package_id         TEXT PRIMARY KEY,
    idempotency_key         TEXT NOT NULL UNIQUE,
    producer_id             TEXT NOT NULL,
    producer_version        TEXT NOT NULL,
    project_key             TEXT NOT NULL,
    analysis_profile        TEXT NOT NULL,
    objective               TEXT NOT NULL,
    status                  TEXT NOT NULL,
    source_digest           TEXT NOT NULL,
    compressed_size_bytes   INTEGER NOT NULL,
    uncompressed_size_bytes INTEGER,
    manifest_json           TEXT NOT NULL,
    package_object_relpath  TEXT,
    preprocess_digest       TEXT,
    result_package_id       TEXT,
    deep_ai_handoff_id      TEXT,
    failure_code            TEXT,
    error_message           TEXT,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL,
    finished_at             TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_business_work_packages_package_digest
    ON business_work_packages(work_package_id, source_digest);
CREATE INDEX IF NOT EXISTS idx_business_work_packages_status_created
    ON business_work_packages(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_business_work_packages_producer_created
    ON business_work_packages(producer_id, created_at DESC);

CREATE TABLE IF NOT EXISTS business_artifacts (
    artifact_row_id    TEXT PRIMARY KEY,
    work_package_id    TEXT NOT NULL REFERENCES business_work_packages(work_package_id) ON DELETE RESTRICT,
    artifact_id        TEXT NOT NULL,
    relative_path      TEXT NOT NULL,
    media_type         TEXT NOT NULL,
    sha256             TEXT NOT NULL,
    size_bytes         INTEGER NOT NULL,
    record_key_field   TEXT,
    created_at         TEXT NOT NULL,
    UNIQUE(work_package_id, artifact_id),
    UNIQUE(work_package_id, relative_path)
);
CREATE INDEX IF NOT EXISTS idx_business_artifacts_package
    ON business_artifacts(work_package_id, created_at);

CREATE TABLE IF NOT EXISTS business_upload_sessions (
    upload_session_id       TEXT PRIMARY KEY,
    work_package_id         TEXT NOT NULL UNIQUE REFERENCES business_work_packages(work_package_id) ON DELETE RESTRICT,
    source_digest           TEXT NOT NULL,
    total_size_bytes        INTEGER NOT NULL,
    verified_size_bytes     INTEGER NOT NULL DEFAULT 0,
    chunk_size_bytes        INTEGER NOT NULL,
    status                  TEXT NOT NULL,
    staging_relpath         TEXT NOT NULL,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL,
    finalized_at            TEXT
);
CREATE INDEX IF NOT EXISTS idx_business_upload_sessions_status
    ON business_upload_sessions(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS business_upload_chunks (
    upload_session_id  TEXT NOT NULL REFERENCES business_upload_sessions(upload_session_id) ON DELETE CASCADE,
    chunk_offset       INTEGER NOT NULL,
    size_bytes         INTEGER NOT NULL,
    sha256             TEXT NOT NULL,
    verified_at        TEXT NOT NULL,
    PRIMARY KEY(upload_session_id, chunk_offset)
);

CREATE TABLE IF NOT EXISTS local_intelligence_runs (
    run_id                 TEXT PRIMARY KEY,
    work_package_id        TEXT NOT NULL REFERENCES business_work_packages(work_package_id) ON DELETE RESTRICT,
    status                 TEXT NOT NULL,
    analysis_profile       TEXT NOT NULL,
    source_digest          TEXT NOT NULL,
    preprocess_digest      TEXT,
    model_adapter_version  TEXT NOT NULL,
    configured_model_id    TEXT NOT NULL,
    template_version       TEXT NOT NULL,
    model_attempts         INTEGER NOT NULL DEFAULT 0,
    quality_outcome        TEXT,
    failure_code           TEXT,
    error_message          TEXT,
    idempotency_key        TEXT NOT NULL UNIQUE,
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL,
    finished_at            TEXT
);
CREATE INDEX IF NOT EXISTS idx_local_intelligence_runs_package_created
    ON local_intelligence_runs(work_package_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_local_intelligence_runs_status_created
    ON local_intelligence_runs(status, created_at DESC);

CREATE TABLE IF NOT EXISTS local_intelligence_chunks (
    chunk_run_id          TEXT PRIMARY KEY,
    run_id                TEXT NOT NULL REFERENCES local_intelligence_runs(run_id) ON DELETE RESTRICT,
    chunk_index           INTEGER NOT NULL,
    context_digest        TEXT NOT NULL,
    result_digest         TEXT,
    status                TEXT NOT NULL,
    model_attempts        INTEGER NOT NULL DEFAULT 0,
    result_json           TEXT,
    failure_code          TEXT,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    UNIQUE(run_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS business_result_packages (
    result_package_id       TEXT PRIMARY KEY,
    work_package_id         TEXT NOT NULL UNIQUE REFERENCES business_work_packages(work_package_id) ON DELETE RESTRICT,
    analysis_profile        TEXT NOT NULL,
    source_digest           TEXT NOT NULL,
    preprocess_digest       TEXT NOT NULL,
    model_adapter_version   TEXT NOT NULL,
    configured_model_id     TEXT NOT NULL,
    template_version        TEXT NOT NULL,
    quality_outcome         TEXT NOT NULL,
    result_digest           TEXT NOT NULL UNIQUE,
    package_relpath         TEXT NOT NULL,
    result_json             TEXT NOT NULL,
    warnings_json           TEXT NOT NULL,
    created_at              TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_business_results_created
    ON business_result_packages(created_at DESC);

CREATE TABLE IF NOT EXISTS deep_ai_handoffs (
    handoff_id              TEXT PRIMARY KEY,
    work_package_id         TEXT NOT NULL UNIQUE REFERENCES business_work_packages(work_package_id) ON DELETE RESTRICT,
    source_digest           TEXT NOT NULL,
    preprocess_digest       TEXT NOT NULL,
    local_result_digest     TEXT NOT NULL,
    quality_reasons_json    TEXT NOT NULL,
    return_schema_json      TEXT NOT NULL,
    package_digest          TEXT NOT NULL UNIQUE,
    package_relpath         TEXT NOT NULL,
    status                  TEXT NOT NULL,
    created_at              TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_deep_ai_handoffs_status_created
    ON deep_ai_handoffs(status, created_at DESC);
"""
