"""Schema 21: immutable Core-owned frugal coding escalation decisions."""

MIGRATION_021 = r"""
CREATE TABLE IF NOT EXISTS deep_ai_frugal_decisions (
    decision_id TEXT PRIMARY KEY,
    goal_id TEXT NOT NULL,
    decision_digest TEXT NOT NULL UNIQUE,
    policy_version TEXT NOT NULL,
    chosen_provider TEXT NOT NULL,
    decision_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_deep_ai_frugal_decisions_goal_created
    ON deep_ai_frugal_decisions(goal_id, created_at DESC, decision_id DESC);
"""
