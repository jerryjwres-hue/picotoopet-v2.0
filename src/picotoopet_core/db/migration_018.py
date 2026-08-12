"""2.3.25.1 controlled Promotion / rollback governance persistence."""

from __future__ import annotations


MIGRATION_018 = r"""
CREATE TABLE IF NOT EXISTS quality_promotions (
    promotion_id TEXT PRIMARY KEY,
    shadow_run_id TEXT NOT NULL UNIQUE,
    candidate_id TEXT NOT NULL,
    project_key TEXT NOT NULL,
    candidate_class TEXT NOT NULL,
    candidate_digest TEXT NOT NULL CHECK(length(candidate_digest) = 64),
    shadow_report_digest TEXT NOT NULL CHECK(length(shadow_report_digest) = 64),
    evaluation_report_digest TEXT NOT NULL CHECK(length(evaluation_report_digest) = 64),
    snapshot_digest TEXT NOT NULL CHECK(length(snapshot_digest) = 64),
    promotion_profile_id TEXT NOT NULL CHECK(promotion_profile_id = 'quality.promotion.v1'),
    slot_key TEXT NOT NULL CHECK(length(slot_key) = 64),
    version_no INTEGER NOT NULL CHECK(version_no >= 1),
    proposal_digest TEXT NOT NULL UNIQUE CHECK(length(proposal_digest) = 64),
    status TEXT NOT NULL CHECK(status IN (
        'AwaitingApproval', 'Active', 'Superseded', 'RolledBack', 'Rejected', 'Cancelled'
    )),
    supersedes_promotion_id TEXT,
    created_at TEXT NOT NULL,
    activated_at TEXT,
    rolled_back_at TEXT,
    FOREIGN KEY(shadow_run_id) REFERENCES quality_shadow_runs(shadow_run_id) ON DELETE RESTRICT,
    FOREIGN KEY(candidate_id) REFERENCES quality_improvement_candidates(candidate_id) ON DELETE RESTRICT,
    FOREIGN KEY(supersedes_promotion_id) REFERENCES quality_promotions(promotion_id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_quality_promotions_slot_version
ON quality_promotions(slot_key, version_no);

CREATE UNIQUE INDEX IF NOT EXISTS ux_quality_promotions_active_slot
ON quality_promotions(slot_key)
WHERE status = 'Active';

CREATE INDEX IF NOT EXISTS idx_quality_promotions_project_class_created
ON quality_promotions(project_key, candidate_class, created_at DESC);

CREATE TABLE IF NOT EXISTS quality_promotion_approval_requests (
    approval_request_id TEXT PRIMARY KEY,
    promotion_id TEXT NOT NULL,
    approval_kind TEXT NOT NULL CHECK(approval_kind IN ('PromotionActivation', 'PromotionRollback')),
    request_digest TEXT NOT NULL UNIQUE CHECK(length(request_digest) = 64),
    status TEXT NOT NULL CHECK(status IN ('Pending', 'Approved', 'Rejected', 'Cancelled', 'Expired')),
    rollback_reason_code TEXT CHECK(
        rollback_reason_code IS NULL OR rollback_reason_code IN (
            'RegressionObserved', 'UnexpectedImpact', 'OperatorDecision'
        )
    ),
    restore_promotion_id TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    resolved_at TEXT,
    FOREIGN KEY(promotion_id) REFERENCES quality_promotions(promotion_id) ON DELETE RESTRICT,
    FOREIGN KEY(restore_promotion_id) REFERENCES quality_promotions(promotion_id) ON DELETE RESTRICT,
    UNIQUE(promotion_id, approval_kind)
);

CREATE INDEX IF NOT EXISTS idx_quality_promotion_approval_requests_promotion_kind
ON quality_promotion_approval_requests(promotion_id, approval_kind);

CREATE TABLE IF NOT EXISTS quality_promotion_decisions (
    decision_id TEXT PRIMARY KEY,
    approval_request_id TEXT NOT NULL UNIQUE,
    promotion_id TEXT NOT NULL,
    decision TEXT NOT NULL CHECK(decision IN ('Approved', 'Rejected', 'Cancelled')),
    request_digest TEXT NOT NULL CHECK(length(request_digest) = 64),
    idempotency_key TEXT NOT NULL,
    decision_digest TEXT NOT NULL UNIQUE CHECK(length(decision_digest) = 64),
    created_at TEXT NOT NULL,
    FOREIGN KEY(approval_request_id) REFERENCES quality_promotion_approval_requests(approval_request_id) ON DELETE RESTRICT,
    FOREIGN KEY(promotion_id) REFERENCES quality_promotions(promotion_id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_quality_promotion_decisions_idempotency
ON quality_promotion_decisions(idempotency_key);

CREATE INDEX IF NOT EXISTS idx_quality_promotion_decisions_promotion_created
ON quality_promotion_decisions(promotion_id, created_at ASC);

CREATE TABLE IF NOT EXISTS quality_promotion_rollbacks (
    rollback_id TEXT PRIMARY KEY,
    promotion_id TEXT NOT NULL UNIQUE,
    restore_promotion_id TEXT,
    approval_request_id TEXT NOT NULL UNIQUE,
    rollback_reason_code TEXT NOT NULL CHECK(rollback_reason_code IN (
        'RegressionObserved', 'UnexpectedImpact', 'OperatorDecision'
    )),
    request_digest TEXT NOT NULL CHECK(length(request_digest) = 64),
    rollback_digest TEXT NOT NULL UNIQUE CHECK(length(rollback_digest) = 64),
    created_at TEXT NOT NULL,
    FOREIGN KEY(promotion_id) REFERENCES quality_promotions(promotion_id) ON DELETE RESTRICT,
    FOREIGN KEY(restore_promotion_id) REFERENCES quality_promotions(promotion_id) ON DELETE RESTRICT,
    FOREIGN KEY(approval_request_id) REFERENCES quality_promotion_approval_requests(approval_request_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_quality_promotion_rollbacks_promotion_created
ON quality_promotion_rollbacks(promotion_id, created_at ASC);
"""
