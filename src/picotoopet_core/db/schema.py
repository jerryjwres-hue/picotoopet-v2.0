"""PicotooPet SQLite 数据库结构与增量迁移。"""

MIGRATION_001 = r"""
CREATE TABLE IF NOT EXISTS schema_migrations (
    version       INTEGER PRIMARY KEY,
    applied_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    project_id        TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    project_type      TEXT NOT NULL,
    source_app        TEXT NOT NULL,
    classification    TEXT NOT NULL,
    workspace_root    TEXT,
    status            TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id         TEXT PRIMARY KEY,
    project_id          TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
    artifact_type       TEXT NOT NULL,
    classification      TEXT NOT NULL,
    source_path         TEXT,
    stored_object_hash  TEXT,
    media_type          TEXT,
    size_bytes          INTEGER,
    sha256              TEXT,
    is_original         INTEGER NOT NULL DEFAULT 0,
    cloud_policy        TEXT NOT NULL DEFAULT 'local_only',
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id            TEXT PRIMARY KEY,
    parent_task_id     TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    project_id         TEXT REFERENCES projects(project_id) ON DELETE RESTRICT,
    task_type          TEXT NOT NULL,
    status             TEXT NOT NULL,
    priority           INTEGER NOT NULL DEFAULT 100,
    resource_tag       TEXT,
    idempotency_key    TEXT,
    dedupe_key         TEXT,
    payload_json       TEXT NOT NULL,
    result_id          TEXT,
    attempt_count      INTEGER NOT NULL DEFAULT 0,
    max_attempts       INTEGER NOT NULL DEFAULT 3,
    timeout_seconds    INTEGER NOT NULL DEFAULT 3600,
    not_before         TEXT,
    lease_owner        TEXT,
    lease_expires_at   TEXT,
    approval_id        TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    started_at         TEXT,
    finished_at        TEXT,
    error_code         TEXT,
    error_message      TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_idempotency_key
    ON tasks(idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tasks_status_priority
    ON tasks(status, priority, created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_dedupe_key
    ON tasks(dedupe_key) WHERE dedupe_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS task_dependencies (
    task_id             TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    depends_on_task_id  TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
    dependency_policy   TEXT NOT NULL DEFAULT 'all_success',
    PRIMARY KEY (task_id, depends_on_task_id)
);

CREATE TABLE IF NOT EXISTS task_attempts (
    attempt_id          TEXT PRIMARY KEY,
    task_id             TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    attempt_number      INTEGER NOT NULL,
    worker_id           TEXT,
    started_at          TEXT NOT NULL,
    finished_at         TEXT,
    status              TEXT NOT NULL,
    error_code          TEXT,
    error_message       TEXT,
    metrics_json        TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS task_events (
    event_id            TEXT PRIMARY KEY,
    task_id             TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    from_status         TEXT,
    to_status           TEXT NOT NULL,
    reason              TEXT,
    trace_id            TEXT,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approvals (
    approval_id         TEXT PRIMARY KEY,
    task_id             TEXT REFERENCES tasks(task_id) ON DELETE RESTRICT,
    approval_type       TEXT NOT NULL,
    scope_json          TEXT NOT NULL,
    status              TEXT NOT NULL,
    token_hash          TEXT NOT NULL,
    requested_by        TEXT NOT NULL,
    resolved_by         TEXT,
    expires_at          TEXT NOT NULL,
    requested_at        TEXT NOT NULL,
    resolved_at         TEXT,
    decision_reason     TEXT
);

CREATE TABLE IF NOT EXISTS results (
    result_id           TEXT PRIMARY KEY,
    project_id          TEXT REFERENCES projects(project_id) ON DELETE RESTRICT,
    task_id             TEXT REFERENCES tasks(task_id) ON DELETE RESTRICT,
    result_type         TEXT NOT NULL,
    object_hash         TEXT NOT NULL,
    manifest_json       TEXT NOT NULL,
    schema_version      TEXT NOT NULL,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    audit_id               TEXT PRIMARY KEY,
    trace_id               TEXT NOT NULL,
    actor_type             TEXT NOT NULL,
    actor_id               TEXT NOT NULL,
    action                 TEXT NOT NULL,
    resource_type          TEXT NOT NULL,
    resource_id            TEXT NOT NULL,
    decision               TEXT NOT NULL,
    reason_code            TEXT,
    details_redacted_json  TEXT NOT NULL,
    previous_hash          TEXT,
    event_hash             TEXT NOT NULL,
    created_at             TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    idempotency_key    TEXT PRIMARY KEY,
    resource_type      TEXT NOT NULL,
    resource_id        TEXT NOT NULL,
    created_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS device_pairings (
    device_id          TEXT PRIMARY KEY,
    device_name        TEXT NOT NULL,
    token_hash         TEXT NOT NULL,
    permissions_json   TEXT NOT NULL,
    status             TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    last_seen_at       TEXT
);

CREATE TABLE IF NOT EXISTS service_health (
    service_name       TEXT PRIMARY KEY,
    status             TEXT NOT NULL,
    details_json       TEXT NOT NULL,
    checked_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_outbox (
    outbox_id          TEXT PRIMARY KEY,
    topic              TEXT NOT NULL,
    payload_json       TEXT NOT NULL,
    trace_id           TEXT,
    created_at         TEXT NOT NULL,
    claimed_at         TEXT,
    claimed_by         TEXT,
    delivered_at       TEXT,
    delivery_attempts  INTEGER NOT NULL DEFAULT 0
);
"""

MIGRATION_002 = r"""
ALTER TABLE tasks
ADD COLUMN cloud_policy TEXT NOT NULL DEFAULT 'local_only';
"""

MIGRATION_003 = r"""
CREATE TABLE IF NOT EXISTS handoffs (
    handoff_id                 TEXT PRIMARY KEY,
    template_id                TEXT NOT NULL,
    title                      TEXT NOT NULL,
    objective_summary          TEXT NOT NULL,
    status                     TEXT NOT NULL,
    request_digest             TEXT NOT NULL,
    package_digest             TEXT NOT NULL,
    manifest_json              TEXT NOT NULL,
    preview_json               TEXT NOT NULL,
    approval_id                TEXT REFERENCES approvals(approval_id) ON DELETE RESTRICT,
    prepare_idempotency_key    TEXT NOT NULL UNIQUE,
    approval_idempotency_key   TEXT UNIQUE,
    created_at                 TEXT NOT NULL,
    updated_at                 TEXT NOT NULL,
    expires_at                 TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_handoffs_status_created
    ON handoffs(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_handoffs_approval_id
    ON handoffs(approval_id) WHERE approval_id IS NOT NULL;
"""

MIGRATION_004 = r"""
CREATE TABLE IF NOT EXISTS returns (
    return_id                 TEXT PRIMARY KEY,
    handoff_id                TEXT NOT NULL REFERENCES handoffs(handoff_id) ON DELETE RESTRICT,
    status                    TEXT NOT NULL,
    provider                  TEXT NOT NULL,
    request_digest            TEXT NOT NULL,
    package_digest            TEXT NOT NULL,
    manifest_digest           TEXT NOT NULL,
    changed_file_count        INTEGER NOT NULL,
    event_count               INTEGER NOT NULL,
    validation_checks_json    TEXT NOT NULL,
    preview_json              TEXT NOT NULL,
    quarantine_code           TEXT,
    idempotency_key           TEXT NOT NULL UNIQUE,
    created_at                TEXT NOT NULL,
    updated_at                TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_returns_handoff_created
    ON returns(handoff_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_returns_status_created
    ON returns(status, created_at DESC);
"""
