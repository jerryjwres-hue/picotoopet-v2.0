"""Migration 19: durable autonomous Goal metadata over existing workflows."""

MIGRATION_019 = """
CREATE TABLE IF NOT EXISTS autonomous_goals (
    goal_id          TEXT PRIMARY KEY,
    parent_goal_id   TEXT REFERENCES autonomous_goals(goal_id) ON DELETE SET NULL,
    workflow_id      TEXT,
    origin           TEXT NOT NULL,
    intent_type      TEXT NOT NULL,
    priority_class   TEXT NOT NULL,
    objective        TEXT NOT NULL,
    constraints_json TEXT NOT NULL,
    budget_class     TEXT NOT NULL,
    pinned           INTEGER NOT NULL DEFAULT 0,
    score            REAL,
    status           TEXT NOT NULL,
    idempotency_key  TEXT NOT NULL UNIQUE,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_autonomous_goals_status_priority
ON autonomous_goals(status, priority_class, created_at);

CREATE INDEX IF NOT EXISTS idx_autonomous_goals_parent
ON autonomous_goals(parent_goal_id, created_at);

CREATE INDEX IF NOT EXISTS idx_autonomous_goals_workflow
ON autonomous_goals(workflow_id) WHERE workflow_id IS NOT NULL;
"""
