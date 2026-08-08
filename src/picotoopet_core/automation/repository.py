"""SQLite repository for durable automation facts."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from sqlite3 import Row
from uuid import uuid4

from picotoopet_core.db.database import Database

from .dag import topological_order
from .models import (
    ArtifactProvenanceCreate,
    CapabilityRecord,
    CapabilityRegistration,
    QualityDecision,
    QualityDecisionRecord,
    QualityOutcome,
    WorkflowContinuationCreate,
    WorkflowCreate,
    WorkflowRecord,
    WorkflowStatus,
    WorkflowStepRecord,
    WorkflowStepStatus,
)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: object) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


class AutomationRepository:
    """Transactional fact store; orchestration decisions live in WorkflowService."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def create_workflow(self, request: WorkflowCreate) -> WorkflowRecord:
        graph = {step.step_key: tuple(step.depends_on) for step in request.steps}
        order = topological_order(graph)
        ordinal = {key: index for index, key in enumerate(order)}
        existing = self.database.fetchone(
            "SELECT workflow_id FROM workflow_runs WHERE idempotency_key = ?",
            (request.idempotency_key,),
        )
        if existing is not None:
            return self.get_workflow(existing["workflow_id"])

        workflow_id = str(uuid4())
        now = datetime.now(UTC)
        with self.database.transaction() as connection:
            existing = connection.execute(
                "SELECT workflow_id FROM workflow_runs WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                workflow_id = existing["workflow_id"]
            else:
                connection.execute(
                    """
                    INSERT INTO workflow_runs (
                        workflow_id, project_id, name, status, priority, max_concurrency,
                        idempotency_key, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        workflow_id,
                        request.project_id,
                        request.name,
                        WorkflowStatus.READY.value,
                        request.priority,
                        request.max_concurrency,
                        request.idempotency_key,
                        now.isoformat(),
                        now.isoformat(),
                    ),
                )
                by_key = {step.step_key: step for step in request.steps}
                for key in order:
                    step = by_key[key]
                    status = (
                        WorkflowStepStatus.READY
                        if not step.depends_on
                        else WorkflowStepStatus.BLOCKED
                    )
                    connection.execute(
                        """
                        INSERT INTO workflow_steps (
                            workflow_id, step_key, ordinal, task_type, required_capability,
                            status, payload_json, attempt_count, max_attempts, timeout_seconds,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                        """,
                        (
                            workflow_id,
                            step.step_key,
                            ordinal[step.step_key],
                            step.task_type,
                            step.required_capability,
                            status.value,
                            _json(step.payload),
                            step.max_attempts,
                            step.timeout_seconds,
                            now.isoformat(),
                            now.isoformat(),
                        ),
                    )
                    for dependency in step.depends_on:
                        connection.execute(
                            """
                            INSERT INTO workflow_step_dependencies (
                                workflow_id, step_key, depends_on_step_key
                            ) VALUES (?, ?, ?)
                            """,
                            (workflow_id, step.step_key, dependency),
                        )
                self._insert_checkpoint(
                    connection,
                    workflow_id=workflow_id,
                    step_key=None,
                    state={
                        "event": "workflow.created",
                        "status": WorkflowStatus.READY.value,
                        "step_order": order,
                    },
                    created_at=now,
                )
        return self.get_workflow(workflow_id)

    def get_workflow(self, workflow_id: str) -> WorkflowRecord:
        row = self.database.fetchone(
            "SELECT * FROM workflow_runs WHERE workflow_id = ?",
            (workflow_id,),
        )
        if row is None:
            raise KeyError(f"workflow not found: {workflow_id}")
        steps = self.database.fetchall(
            "SELECT * FROM workflow_steps WHERE workflow_id = ? ORDER BY ordinal, step_key",
            (workflow_id,),
        )
        dependencies = self.database.fetchall(
            """
            SELECT step_key, depends_on_step_key
            FROM workflow_step_dependencies
            WHERE workflow_id = ?
            ORDER BY step_key, depends_on_step_key
            """,
            (workflow_id,),
        )
        by_step: dict[str, list[str]] = {}
        for dependency in dependencies:
            by_step.setdefault(dependency["step_key"], []).append(
                dependency["depends_on_step_key"]
            )
        return self._row_to_workflow(
            row,
            [self._row_to_step(step, by_step.get(step["step_key"], [])) for step in steps],
        )

    def list_workflows(self, *, limit: int = 200) -> list[WorkflowRecord]:
        bounded = max(1, min(int(limit), 500))
        rows = self.database.fetchall(
            "SELECT workflow_id FROM workflow_runs ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (bounded,),
        )
        return [self.get_workflow(row["workflow_id"]) for row in rows]

    def update_workflow_status(
        self,
        workflow_id: str,
        status: WorkflowStatus,
        *,
        failure_code: str | None = None,
        finished: bool = False,
    ) -> None:
        now = datetime.now(UTC)
        self.database.execute(
            """
            UPDATE workflow_runs
            SET status = ?, failure_code = ?, updated_at = ?,
                started_at = CASE WHEN ? = ? THEN COALESCE(started_at, ?) ELSE started_at END,
                finished_at = CASE WHEN ? THEN COALESCE(finished_at, ?) ELSE finished_at END
            WHERE workflow_id = ?
            """,
            (
                status.value,
                failure_code,
                now.isoformat(),
                status.value,
                WorkflowStatus.RUNNING.value,
                now.isoformat(),
                1 if finished else 0,
                now.isoformat(),
                workflow_id,
            ),
        )

    def update_step(
        self,
        workflow_id: str,
        step_key: str,
        *,
        status: WorkflowStepStatus,
        task_id: str | None = None,
        increment_attempt: bool = False,
        failure_code: str | None = None,
        error_message: str | None = None,
        finished: bool = False,
    ) -> None:
        now = datetime.now(UTC)
        self.database.execute(
            """
            UPDATE workflow_steps
            SET status = ?, task_id = COALESCE(?, task_id),
                attempt_count = attempt_count + ?, failure_code = ?, error_message = ?,
                updated_at = ?,
                finished_at = CASE WHEN ? THEN COALESCE(finished_at, ?) ELSE NULL END
            WHERE workflow_id = ? AND step_key = ?
            """,
            (
                status.value,
                task_id,
                1 if increment_attempt else 0,
                failure_code,
                error_message,
                now.isoformat(),
                1 if finished else 0,
                now.isoformat(),
                workflow_id,
                step_key,
            ),
        )

    def record_checkpoint(
        self,
        workflow_id: str,
        *,
        step_key: str | None,
        state: dict[str, object],
    ) -> str:
        now = datetime.now(UTC)
        with self.database.transaction() as connection:
            return self._insert_checkpoint(
                connection,
                workflow_id=workflow_id,
                step_key=step_key,
                state=state,
                created_at=now,
            )

    def latest_checkpoint_digest(self, workflow_id: str) -> str:
        row = self.database.fetchone(
            """
            SELECT digest FROM workflow_checkpoints
            WHERE workflow_id = ? ORDER BY sequence DESC LIMIT 1
            """,
            (workflow_id,),
        )
        if row is None:
            raise KeyError(f"workflow checkpoint not found: {workflow_id}")
        return row["digest"]

    def upsert_capability(self, registration: CapabilityRegistration) -> CapabilityRecord:
        now = datetime.now(UTC)
        heartbeat = registration.heartbeat_at.astimezone(UTC)
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO capability_registrations (
                    worker_id, capability, task_types_json, healthy, metadata_json,
                    registered_at, heartbeat_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(worker_id, capability) DO UPDATE SET
                    task_types_json = excluded.task_types_json,
                    healthy = excluded.healthy,
                    metadata_json = excluded.metadata_json,
                    heartbeat_at = excluded.heartbeat_at
                """,
                (
                    registration.worker_id,
                    registration.capability,
                    _json(sorted(set(registration.task_types))),
                    1 if registration.healthy else 0,
                    _json(registration.metadata),
                    now.isoformat(),
                    heartbeat.isoformat(),
                ),
            )
        row = self.database.fetchone(
            "SELECT * FROM capability_registrations WHERE worker_id = ? AND capability = ?",
            (registration.worker_id, registration.capability),
        )
        assert row is not None
        return self._row_to_capability(row)

    def list_capabilities(self) -> list[CapabilityRecord]:
        rows = self.database.fetchall(
            "SELECT * FROM capability_registrations ORDER BY capability, worker_id"
        )
        return [self._row_to_capability(row) for row in rows]

    def record_quality_decision(self, decision: QualityDecision) -> QualityDecisionRecord:
        record = QualityDecisionRecord(**decision.model_dump())
        self.database.execute(
            """
            INSERT INTO quality_decisions (
                decision_id, workflow_id, step_key, outcome, rule_id, evidence_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.decision_id,
                record.workflow_id,
                record.step_key,
                record.outcome.value,
                record.rule_id,
                _json(record.evidence),
                record.created_at.isoformat(),
            ),
        )
        return record

    def record_artifact_provenance(self, request: ArtifactProvenanceCreate) -> None:
        existing = self.database.fetchone(
            "SELECT sha256 FROM artifact_provenance WHERE artifact_id = ?",
            (request.artifact_id,),
        )
        if existing is not None and existing["sha256"] != request.sha256:
            raise ValueError("artifact provenance digest is immutable")
        now = datetime.now(UTC)
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO artifact_provenance (
                    artifact_id, workflow_id, step_key, task_id, sha256, capability,
                    model_id, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(artifact_id) DO NOTHING
                """,
                (
                    request.artifact_id,
                    request.workflow_id,
                    request.step_key,
                    request.task_id,
                    request.sha256,
                    request.capability,
                    request.model_id,
                    _json(request.metadata),
                    now.isoformat(),
                ),
            )
            for parent_id in sorted(set(request.parent_artifact_ids)):
                connection.execute(
                    """
                    INSERT OR IGNORE INTO artifact_links (
                        artifact_id, parent_artifact_id, relation, created_at
                    ) VALUES (?, ?, 'input', ?)
                    """,
                    (request.artifact_id, parent_id, now.isoformat()),
                )

    def create_continuation(self, request: WorkflowContinuationCreate) -> str:
        if self.latest_checkpoint_digest(request.workflow_id) != request.checkpoint_digest:
            raise ValueError("workflow checkpoint digest mismatch")
        continuation_id = str(uuid4())
        now = datetime.now(UTC)
        self.database.execute(
            """
            INSERT INTO workflow_handoff_continuations (
                continuation_id, workflow_id, step_key, checkpoint_digest,
                handoff_id, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'WaitingReturn', ?, ?)
            """,
            (
                continuation_id,
                request.workflow_id,
                request.step_key,
                request.checkpoint_digest,
                request.handoff_id,
                now.isoformat(),
                now.isoformat(),
            ),
        )
        return continuation_id

    def bind_return(self, handoff_id: str, return_id: str, checkpoint_digest: str) -> None:
        row = self.database.fetchone(
            "SELECT * FROM workflow_handoff_continuations WHERE handoff_id = ?",
            (handoff_id,),
        )
        if row is None:
            raise KeyError(f"workflow continuation not found for handoff: {handoff_id}")
        if row["checkpoint_digest"] != checkpoint_digest:
            raise ValueError("workflow checkpoint digest mismatch")
        self.database.execute(
            """
            UPDATE workflow_handoff_continuations
            SET return_id = ?, status = 'ReturnBound', updated_at = ?
            WHERE handoff_id = ?
            """,
            (return_id, datetime.now(UTC).isoformat(), handoff_id),
        )

    def apply_quality_outcome(self, decision: QualityDecision) -> None:
        mapping = {
            QualityOutcome.RETRY: WorkflowStepStatus.RETRY_WAITING,
            QualityOutcome.NEEDS_DEEP_AI: WorkflowStepStatus.NEEDS_DEEP_AI,
            QualityOutcome.NEEDS_HUMAN: WorkflowStepStatus.NEEDS_HUMAN,
            QualityOutcome.REJECT: WorkflowStepStatus.REJECTED,
        }
        target = mapping.get(decision.outcome)
        if target is not None:
            self.update_step(
                decision.workflow_id,
                decision.step_key,
                status=target,
                finished=decision.outcome is QualityOutcome.REJECT,
            )

    def recent_diagnostic_rows(self, *, limit: int = 100) -> list[Row]:
        bounded = max(1, min(int(limit), 500))
        return self.database.fetchall(
            """
            SELECT ws.workflow_id, ws.step_key, ws.task_id, ws.status,
                   COALESCE(ws.failure_code, t.error_code) AS error_code,
                   COALESCE(ws.error_message, t.error_message) AS error_message,
                   te.trace_id AS trace_id, ws.updated_at
            FROM workflow_steps ws
            LEFT JOIN tasks t ON t.task_id = ws.task_id
            LEFT JOIN task_events te ON te.rowid = (
                SELECT e.rowid FROM task_events e
                WHERE e.task_id = ws.task_id
                ORDER BY e.rowid DESC LIMIT 1
            )
            WHERE ws.status IN (?, ?, ?, ?, ?)
            ORDER BY ws.updated_at DESC
            LIMIT ?
            """,
            (
                WorkflowStepStatus.FAILED.value,
                WorkflowStepStatus.CANCELLED.value,
                WorkflowStepStatus.NEEDS_HUMAN.value,
                WorkflowStepStatus.NEEDS_DEEP_AI.value,
                WorkflowStepStatus.REJECTED.value,
                bounded,
            ),
        )

    def _insert_checkpoint(
        self,
        connection,  # sqlite Connection; kept untyped to avoid public sqlite coupling.
        *,
        workflow_id: str,
        step_key: str | None,
        state: dict[str, object],
        created_at: datetime,
    ) -> str:
        sequence_row = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM workflow_checkpoints WHERE workflow_id = ?",
            (workflow_id,),
        ).fetchone()
        sequence = int(sequence_row[0])
        state_json = _json(state)
        digest = _digest(
            {
                "workflow_id": workflow_id,
                "step_key": step_key,
                "sequence": sequence,
                "state": json.loads(state_json),
            }
        )
        connection.execute(
            """
            INSERT INTO workflow_checkpoints (
                checkpoint_id, workflow_id, step_key, sequence, digest, state_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                workflow_id,
                step_key,
                sequence,
                digest,
                state_json,
                created_at.isoformat(),
            ),
        )
        return digest

    @staticmethod
    def _row_to_workflow(row: Row, steps: list[WorkflowStepRecord]) -> WorkflowRecord:
        return WorkflowRecord(
            workflow_id=row["workflow_id"],
            project_id=row["project_id"],
            name=row["name"],
            status=WorkflowStatus(row["status"]),
            priority=int(row["priority"]),
            max_concurrency=int(row["max_concurrency"]),
            idempotency_key=row["idempotency_key"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            started_at=(
                datetime.fromisoformat(row["started_at"]) if row["started_at"] else None
            ),
            finished_at=(
                datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None
            ),
            failure_code=row["failure_code"],
            steps=steps,
        )

    @staticmethod
    def _row_to_step(row: Row, dependencies: list[str]) -> WorkflowStepRecord:
        return WorkflowStepRecord(
            workflow_id=row["workflow_id"],
            step_key=row["step_key"],
            ordinal=int(row["ordinal"]),
            task_type=row["task_type"],
            required_capability=row["required_capability"],
            depends_on=dependencies,
            payload=json.loads(row["payload_json"]),
            status=WorkflowStepStatus(row["status"]),
            task_id=row["task_id"],
            attempt_count=int(row["attempt_count"]),
            max_attempts=int(row["max_attempts"]),
            timeout_seconds=int(row["timeout_seconds"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            finished_at=(
                datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None
            ),
            failure_code=row["failure_code"],
            error_message=row["error_message"],
        )

    @staticmethod
    def _row_to_capability(row: Row) -> CapabilityRecord:
        return CapabilityRecord(
            worker_id=row["worker_id"],
            capability=row["capability"],
            task_types=json.loads(row["task_types_json"]),
            healthy=bool(row["healthy"]),
            metadata=json.loads(row["metadata_json"]),
            registered_at=datetime.fromisoformat(row["registered_at"]),
            heartbeat_at=datetime.fromisoformat(row["heartbeat_at"]),
        )
