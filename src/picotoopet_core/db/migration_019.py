"""2.3.27.1 可恢复任务隐藏状态。"""

MIGRATION_019 = r"""
CREATE TABLE IF NOT EXISTS task_visibility (
    task_id      TEXT PRIMARY KEY REFERENCES tasks(task_id) ON DELETE CASCADE,
    is_hidden    INTEGER NOT NULL DEFAULT 0 CHECK (is_hidden IN (0, 1)),
    updated_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_task_visibility_hidden_updated
    ON task_visibility(is_hidden, updated_at DESC);
"""
