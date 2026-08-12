"""2.3.23.1 offline quality-evaluation persistence."""

from __future__ import annotations


MIGRATION_016 = r"""
CREATE TABLE IF NOT EXISTS quality_evaluation_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    project_key TEXT NOT NULL,
    evaluation_profile_id TEXT NOT NULL,
    stage_profile TEXT,
    start_at TEXT,
    end_at TEXT,
    limit_count INTEGER NOT NULL CHECK(limit_count BETWEEN 1 AND 10000),
    scope_digest TEXT NOT NULL CHECK(length(scope_digest) = 64),
    snapshot_digest TEXT NOT NULL CHECK(length(snapshot_digest) = 64),
    member_count INTEGER NOT NULL CHECK(member_count >= 0),
    created_at TEXT NOT NULL,
    UNIQUE(snapshot_digest)
);

CREATE INDEX IF NOT EXISTS idx_quality_evaluation_snapshots_project_created
ON quality_evaluation_snapshots(project_key, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS ux_quality_evaluation_snapshots_scope_digest
ON quality_evaluation_snapshots(scope_digest, snapshot_digest);

CREATE TABLE IF NOT EXISTS quality_evaluation_snapshot_members (
    snapshot_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    event_id TEXT NOT NULL,
    event_digest TEXT NOT NULL CHECK(length(event_digest) = 64),
    PRIMARY KEY(snapshot_id, ordinal),
    UNIQUE(snapshot_id, event_id),
    FOREIGN KEY(snapshot_id) REFERENCES quality_evaluation_snapshots(snapshot_id) ON DELETE CASCADE,
    FOREIGN KEY(event_id) REFERENCES deep_ai_learning_events(event_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_quality_evaluation_snapshot_members_event
ON quality_evaluation_snapshot_members(event_id);

CREATE TABLE IF NOT EXISTS quality_evaluation_runs (
    evaluation_run_id TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL UNIQUE,
    evaluation_profile_id TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    status TEXT NOT NULL,
    report_digest TEXT NOT NULL CHECK(length(report_digest) = 64),
    created_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY(snapshot_id) REFERENCES quality_evaluation_snapshots(snapshot_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_quality_evaluation_runs_created
ON quality_evaluation_runs(created_at DESC);

CREATE TABLE IF NOT EXISTS quality_evaluation_metrics (
    metric_id TEXT PRIMARY KEY,
    evaluation_run_id TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    value_json TEXT,
    numerator REAL,
    denominator REAL,
    availability TEXT NOT NULL,
    cohort_dimension TEXT,
    cohort_key TEXT,
    cohort_digest TEXT NOT NULL CHECK(length(cohort_digest) = 64),
    FOREIGN KEY(evaluation_run_id) REFERENCES quality_evaluation_runs(evaluation_run_id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_quality_evaluation_metrics_identity
ON quality_evaluation_metrics(
    evaluation_run_id,
    metric_name,
    COALESCE(cohort_dimension, ''),
    COALESCE(cohort_key, '')
);

CREATE INDEX IF NOT EXISTS idx_quality_evaluation_metrics_run
ON quality_evaluation_metrics(evaluation_run_id, cohort_dimension, cohort_key);

CREATE TABLE IF NOT EXISTS quality_improvement_candidates (
    candidate_id TEXT PRIMARY KEY,
    project_key TEXT NOT NULL,
    evaluation_run_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    candidate_class TEXT NOT NULL,
    cohort_dimension TEXT,
    cohort_key TEXT,
    cohort_digest TEXT NOT NULL CHECK(length(cohort_digest) = 64),
    trigger_json TEXT NOT NULL,
    reason_codes_json TEXT NOT NULL,
    status TEXT NOT NULL,
    candidate_digest TEXT NOT NULL CHECK(length(candidate_digest) = 64),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(evaluation_run_id) REFERENCES quality_evaluation_runs(evaluation_run_id) ON DELETE RESTRICT,
    FOREIGN KEY(snapshot_id) REFERENCES quality_evaluation_snapshots(snapshot_id) ON DELETE RESTRICT,
    UNIQUE(evaluation_run_id, rule_version, candidate_class, cohort_digest),
    UNIQUE(candidate_digest)
);

CREATE INDEX IF NOT EXISTS idx_quality_improvement_candidates_run
ON quality_improvement_candidates(evaluation_run_id, status, candidate_class);

CREATE INDEX IF NOT EXISTS idx_quality_improvement_candidates_project
ON quality_improvement_candidates(project_key, created_at DESC);

CREATE TABLE IF NOT EXISTS quality_improvement_candidate_reviews (
    review_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    action TEXT NOT NULL,
    review_digest TEXT NOT NULL CHECK(length(review_digest) = 64),
    created_at TEXT NOT NULL,
    FOREIGN KEY(candidate_id) REFERENCES quality_improvement_candidates(candidate_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_quality_improvement_candidate_reviews_candidate
ON quality_improvement_candidate_reviews(candidate_id, created_at ASC);
"""
