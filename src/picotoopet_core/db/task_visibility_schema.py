"""2.3.27.1 操作员任务可见性 sidecar schema。

该表只保存 UI 可恢复隐藏状态，不改变 PicotooPet Core 已批准的累计 Schema 18。
"""

TASK_VISIBILITY_SCHEMA = r"""
CREATE TABLE IF NOT EXISTS task_visibility (
    task_id      TEXT PRIMARY KEY REFERENCES tasks(task_id) ON DELETE CASCADE,
    is_hidden    INTEGER NOT NULL DEFAULT 0 CHECK (is_hidden IN (0, 1)),
    updated_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_task_visibility_hidden_updated
    ON task_visibility(is_hidden, updated_at DESC);
"""
