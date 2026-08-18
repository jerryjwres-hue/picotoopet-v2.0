"""SQLite repository for durable autonomous Goal metadata."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from sqlite3 import Row
from uuid import uuid4

from picotoopet_core.db.database import Database

from .models import GoalCreate, GoalOrigin, GoalRecord, GoalStatus, PriorityClass


def _json(value: object) -> str:
    """Canonical JSON keeps replay comparisons deterministic."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class AutonomousGoalRepository:
    """Store Goal facts only; queue/workflow execution remains in existing services."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def create(self, request: GoalCreate) -> GoalRecord:
        """Create one replay-safe Goal without creating tasks or workflows."""

        existing = self.database.fetchone(
            "SELECT * FROM autonomous_goals WHERE idempotency_key = ?",
            (request.idempotency_key,),
        )
        if existing is not None:
            self._assert_same_request(existing, request)
            return self._row_to_record(existing)

        now = datetime.now(UTC)
        goal_id = str(uuid4())
        with self.database.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM autonomous_goals WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO autonomous_goals (
                        goal_id, parent_goal_id, workflow_id, origin, intent_type,
                        priority_class, objective, constraints_json, budget_class,
                        pinned, score, status, idempotency_key, created_at, updated_at
                    ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        goal_id,
                        request.parent_goal_id,
                        request.origin.value,
                        request.intent_type,
                        request.priority_class.value,
                        request.objective,
                        _json(request.constraints),
                        request.budget_class,
                        1 if request.pinned else 0,
                        request.score,
                        GoalStatus.READY.value,
                        request.idempotency_key,
                        now.isoformat(),
                        now.isoformat(),
                    ),
                )
            else:
                self._assert_same_request(existing, request)
                goal_id = existing["goal_id"]
        return self.get(goal_id)

    def get(self, goal_id: str) -> GoalRecord:
        """Read one canonical Goal projection."""

        row = self.database.fetchone(
            "SELECT * FROM autonomous_goals WHERE goal_id = ?",
            (goal_id,),
        )
        if row is None:
            raise KeyError(f"autonomous goal not found: {goal_id}")
        return self._row_to_record(row)

    def list(self, *, limit: int = 200) -> list[GoalRecord]:
        """List newest Goals with a bounded result size."""

        bounded = max(1, min(int(limit), 500))
        rows = self.database.fetchall(
            "SELECT * FROM autonomous_goals ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (bounded,),
        )
        return [self._row_to_record(row) for row in rows]

    def bind_workflow(self, goal_id: str, workflow_id: str) -> GoalRecord:
        """Bind an existing Workflow ID once; never create a second scheduler fact."""

        if not workflow_id.strip():
            raise ValueError("workflow_id must not be empty")
        current = self.get(goal_id)
        if current.workflow_id is not None and current.workflow_id != workflow_id:
            raise ValueError("goal is already bound to a different workflow")
        self.database.execute(
            "UPDATE autonomous_goals SET workflow_id = ?, updated_at = ? WHERE goal_id = ?",
            (workflow_id, datetime.now(UTC).isoformat(), goal_id),
        )
        return self.get(goal_id)

    def update_status(self, goal_id: str, status: GoalStatus) -> GoalRecord:
        """Update Goal lifecycle metadata without mutating workflow/task terminal facts."""

        self.get(goal_id)
        self.database.execute(
            "UPDATE autonomous_goals SET status = ?, updated_at = ? WHERE goal_id = ?",
            (status.value, datetime.now(UTC).isoformat(), goal_id),
        )
        return self.get(goal_id)

    @staticmethod
    def _assert_same_request(row: Row, request: GoalCreate) -> None:
        """An idempotency key cannot silently describe a different Goal."""

        stored = {
            "parent_goal_id": row["parent_goal_id"],
            "origin": row["origin"],
            "intent_type": row["intent_type"],
            "priority_class": row["priority_class"],
            "objective": row["objective"],
            "constraints_json": row["constraints_json"],
            "budget_class": row["budget_class"],
            "pinned": bool(row["pinned"]),
            "score": row["score"],
        }
        requested = {
            "parent_goal_id": request.parent_goal_id,
            "origin": request.origin.value,
            "intent_type": request.intent_type,
            "priority_class": request.priority_class.value,
            "objective": request.objective,
            "constraints_json": _json(request.constraints),
            "budget_class": request.budget_class,
            "pinned": request.pinned,
            "score": request.score,
        }
        if stored != requested:
            raise ValueError("idempotency_key is already bound to a different Goal")

    @staticmethod
    def _row_to_record(row: Row) -> GoalRecord:
        return GoalRecord(
            goal_id=row["goal_id"],
            parent_goal_id=row["parent_goal_id"],
            workflow_id=row["workflow_id"],
            origin=GoalOrigin(row["origin"]),
            intent_type=row["intent_type"],
            priority_class=PriorityClass(row["priority_class"]),
            objective=row["objective"],
            constraints=json.loads(row["constraints_json"]),
            budget_class=row["budget_class"],
            pinned=bool(row["pinned"]),
            score=row["score"],
            status=GoalStatus(row["status"]),
            idempotency_key=row["idempotency_key"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
