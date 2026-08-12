"""2.3.24.1 deterministic controlled-shadow persistence."""

from __future__ import annotations


MIGRATION_017 = r"""
CREATE TABLE IF NOT EXISTS quality_shadow_runs (
    shadow_run_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL UNIQUE,
    evaluation_run_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    project_key TEXT NOT NULL,
    candidate_class TEXT NOT NULL,
    candidate_digest TEXT NOT NULL CHECK(length(candidate_digest) = 64),
    snapshot_digest TEXT NOT NULL CHECK(length(snapshot_digest) = 64),
    evaluation_report_digest TEXT NOT NULL CHECK(length(evaluation_report_digest) = 64),
    shadow_profile_id TEXT NOT NULL,
    split_version TEXT NOT NULL,
    status TEXT NOT NULL,
    verdict TEXT NOT NULL,
    input_digest TEXT NOT NULL CHECK(length(input_digest) = 64),
    report_digest TEXT NOT NULL CHECK(length(report_digest) = 64),
    created_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY(candidate_id) REFERENCES quality_improvement_candidates(candidate_id) ON DELETE RESTRICT,
    FOREIGN KEY(evaluation_run_id) REFERENCES quality_evaluation_runs(evaluation_run_id) ON DELETE RESTRICT,
    FOREIGN KEY(snapshot_id) REFERENCES quality_evaluation_snapshots(snapshot_id) ON DELETE RESTRICT,
    UNIQUE(input_digest),
    UNIQUE(report_digest)
);

CREATE INDEX IF NOT EXISTS idx_quality_shadow_runs_project_created
ON quality_shadow_runs(project_key, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_quality_shadow_runs_candidate
ON quality_shadow_runs(candidate_id, created_at DESC);

CREATE TABLE IF NOT EXISTS quality_shadow_arm_metrics (
    metric_id TEXT PRIMARY KEY,
    shadow_run_id TEXT NOT NULL,
    arm TEXT NOT NULL CHECK(arm IN ('baseline', 'shadow')),
    metric_name TEXT NOT NULL,
    value_json TEXT,
    numerator REAL,
    denominator REAL,
    availability TEXT NOT NULL,
    arm_digest TEXT NOT NULL CHECK(length(arm_digest) = 64),
    FOREIGN KEY(shadow_run_id) REFERENCES quality_shadow_runs(shadow_run_id) ON DELETE CASCADE,
    UNIQUE(shadow_run_id, arm, metric_name)
);

CREATE INDEX IF NOT EXISTS idx_quality_shadow_arm_metrics_run_arm
ON quality_shadow_arm_metrics(shadow_run_id, arm, metric_name);

CREATE TABLE IF NOT EXISTS quality_shadow_reviews (
    review_id TEXT PRIMARY KEY,
    shadow_run_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    action TEXT NOT NULL,
    review_digest TEXT NOT NULL CHECK(length(review_digest) = 64),
    created_at TEXT NOT NULL,
    FOREIGN KEY(shadow_run_id) REFERENCES quality_shadow_runs(shadow_run_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_quality_shadow_reviews_run_created
ON quality_shadow_reviews(shadow_run_id, created_at ASC);
"""
