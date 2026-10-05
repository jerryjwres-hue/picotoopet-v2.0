"""Schema 22: durable truthful progress events for Superpower v1.0 tasks."""

MIGRATION_022 = r"""
CREATE TABLE IF NOT EXISTS task_progress_events (
    task_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK(sequence >= 1),
    stage TEXT NOT NULL,
    completed INTEGER NULL CHECK(completed IS NULL OR completed >= 0),
    total INTEGER NULL CHECK(total IS NULL OR total >= 1),
    message TEXT NOT NULL,
    component TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    PRIMARY KEY (task_id, sequence),
    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE,
    CHECK(completed IS NULL OR total IS NOT NULL),
    CHECK(completed IS NULL OR completed <= total)
);
CREATE INDEX IF NOT EXISTS idx_task_progress_events_task_created
    ON task_progress_events(task_id, created_at DESC, sequence DESC);
"""
