"""Migration 9: durable generic workflow automation facts."""

MIGRATION_009 = """
CREATE TABLE IF NOT EXISTS workflow_runs (
    workflow_id TEXT PRIMARY KEY,
    project_id TEXT,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    priority INTEGER NOT NULL,
    max_concurrency INTEGER NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    failure_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    FOREIGN KEY(project_id) REFERENCES projects(project_id)
);

CREATE INDEX IF NOT EXISTS idx_workflow_runs_status_created
ON workflow_runs(status, created_at);

CREATE TABLE IF NOT EXISTS workflow_steps (
    workflow_id TEXT NOT NULL,
    step_key TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    task_type TEXT NOT NULL,
    required_capability TEXT,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    task_id TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL,
    timeout_seconds INTEGER NOT NULL,
    failure_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT,
    PRIMARY KEY(workflow_id, step_key),
    FOREIGN KEY(workflow_id) REFERENCES workflow_runs(workflow_id) ON DELETE CASCADE,
    FOREIGN KEY(task_id) REFERENCES tasks(task_id)
);

CREATE INDEX IF NOT EXISTS idx_workflow_steps_status
ON workflow_steps(workflow_id, status, ordinal);

CREATE TABLE IF NOT EXISTS workflow_step_dependencies (
    workflow_id TEXT NOT NULL,
    step_key TEXT NOT NULL,
    depends_on_step_key TEXT NOT NULL,
    PRIMARY KEY(workflow_id, step_key, depends_on_step_key),
    FOREIGN KEY(workflow_id, step_key)
        REFERENCES workflow_steps(workflow_id, step_key) ON DELETE CASCADE,
    FOREIGN KEY(workflow_id, depends_on_step_key)
        REFERENCES workflow_steps(workflow_id, step_key) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS workflow_checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    step_key TEXT,
    sequence INTEGER NOT NULL,
    digest TEXT NOT NULL,
    state_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(workflow_id, sequence),
    UNIQUE(workflow_id, digest),
    FOREIGN KEY(workflow_id) REFERENCES workflow_runs(workflow_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS artifact_provenance (
    artifact_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    step_key TEXT NOT NULL,
    task_id TEXT,
    sha256 TEXT NOT NULL,
    capability TEXT,
    model_id TEXT,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(artifact_id) REFERENCES artifacts(artifact_id),
    FOREIGN KEY(workflow_id, step_key)
        REFERENCES workflow_steps(workflow_id, step_key),
    FOREIGN KEY(task_id) REFERENCES tasks(task_id)
);

CREATE TABLE IF NOT EXISTS artifact_links (
    artifact_id TEXT NOT NULL,
    parent_artifact_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(artifact_id, parent_artifact_id, relation),
    FOREIGN KEY(artifact_id) REFERENCES artifacts(artifact_id),
    FOREIGN KEY(parent_artifact_id) REFERENCES artifacts(artifact_id)
);

CREATE TABLE IF NOT EXISTS capability_registrations (
    worker_id TEXT NOT NULL,
    capability TEXT NOT NULL,
    task_types_json TEXT NOT NULL,
    healthy INTEGER NOT NULL,
    metadata_json TEXT NOT NULL,
    registered_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    PRIMARY KEY(worker_id, capability)
);

CREATE INDEX IF NOT EXISTS idx_capability_registrations_lookup
ON capability_registrations(capability, healthy, heartbeat_at);

CREATE TABLE IF NOT EXISTS quality_decisions (
    decision_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    step_key TEXT NOT NULL,
    outcome TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(workflow_id, step_key)
        REFERENCES workflow_steps(workflow_id, step_key) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_quality_decisions_step
ON quality_decisions(workflow_id, step_key, created_at);

CREATE TABLE IF NOT EXISTS workflow_handoff_continuations (
    continuation_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    step_key TEXT NOT NULL,
    checkpoint_digest TEXT NOT NULL,
    handoff_id TEXT NOT NULL UNIQUE,
    return_id TEXT UNIQUE,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(workflow_id, step_key)
        REFERENCES workflow_steps(workflow_id, step_key) ON DELETE CASCADE,
    FOREIGN KEY(handoff_id) REFERENCES handoffs(handoff_id),
    FOREIGN KEY(return_id) REFERENCES returns(return_id)
);
"""
