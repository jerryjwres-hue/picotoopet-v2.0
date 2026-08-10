"""Migration 10: controlled remote publication and Draft PR facts."""

MIGRATION_010 = """
CREATE TABLE IF NOT EXISTS provider_publication_candidates (
    publication_candidate_id TEXT PRIMARY KEY,
    commit_candidate_id TEXT NOT NULL UNIQUE
        REFERENCES provider_commit_candidates(commit_candidate_id) ON DELETE RESTRICT,
    session_id TEXT NOT NULL REFERENCES provider_sessions(session_id) ON DELETE RESTRICT,
    handoff_id TEXT NOT NULL REFERENCES handoffs(handoff_id) ON DELETE RESTRICT,
    status TEXT NOT NULL,
    repo_url TEXT NOT NULL,
    repository_slug TEXT NOT NULL,
    base_ref TEXT NOT NULL,
    base_commit TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    change_set_digest TEXT NOT NULL,
    remote_ref TEXT NOT NULL UNIQUE,
    remote_branch TEXT NOT NULL UNIQUE,
    approval_id TEXT NOT NULL UNIQUE REFERENCES approvals(approval_id) ON DELETE RESTRICT,
    idempotency_key TEXT NOT NULL UNIQUE,
    pr_title_digest TEXT NOT NULL,
    pr_body_digest TEXT NOT NULL,
    pr_number INTEGER,
    pr_url TEXT,
    pr_head_sha TEXT,
    validation_json TEXT NOT NULL,
    failure_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT,
    preview_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_provider_publication_status_created
ON provider_publication_candidates(status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_provider_publication_session_created
ON provider_publication_candidates(session_id, created_at DESC);
"""
