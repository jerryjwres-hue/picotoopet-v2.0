"""事务化执行租约、产物登记和审片。"""

import base64
import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from sqlite3 import Connection
from uuid import uuid4

from picotoopet_core.audit.writer import AuditWriter, canonical_hash
from picotoopet_core.domain.enums import TaskStatus
from picotoopet_core.domain.executor import (
    IMPORTED_TASK_TYPE,
    TASK_RUNNERS,
    ArtifactDecision,
    ArtifactList,
    ExecutorArtifact,
    ExecutorComplete,
    ExecutorFail,
    ExecutorHeartbeat,
    ExecutorLease,
    ExecutorReport,
    ReviewedArtifact,
    ThumbnailContent,
    ThumbnailRecord,
)
from picotoopet_core.domain.models import TaskCreate, TaskRecord
from picotoopet_core.queue.repository import QueueRepository
from picotoopet_core.queue.state_machine import InvalidTransitionError


class ExecutorService:
    def __init__(self, queue: QueueRepository, audit: AuditWriter):
        self.queue = queue
        self.audit = audit

    def lease(self, body: ExecutorLease, trace_id: str) -> TaskRecord | None:
        tags = tuple(body.resource_tags)
        types = tuple(TASK_RUNNERS)
        self.queue.recover_expired_leases(resource_tags=tags, task_types=types)
        filters, params = self.queue._lease_filters(tags, types, body.resume_task_id)
        with self.queue.database.transaction() as db:
            existing = db.execute(
                f"""
                SELECT tasks.* FROM tasks JOIN executor_leases USING (task_id)
                WHERE status = ? AND lease_owner = ? AND lease_expires_at >= ? {filters}
                ORDER BY updated_at DESC LIMIT 1
                """,
                (TaskStatus.RUNNING.value, body.worker_id, datetime.now(UTC).isoformat(), *params),
            ).fetchone()
            if existing is not None:
                return self.queue._row_to_record(existing)

            retrying = db.execute(
                f"SELECT tasks.task_id FROM tasks WHERE status = ? {filters}",
                (TaskStatus.RETRYING.value, *params),
            ).fetchall()
            for row in retrying:
                self.queue.transition_in_transaction(
                    db,
                    task_id=row["task_id"],
                    target=TaskStatus.QUEUED,
                    reason="executor_retry",
                    trace_id=trace_id,
                )
            task = self.queue.lease_next(
                body.worker_id,
                body.lease_seconds,
                trace_id=trace_id,
                resource_tags=tags,
                task_types=types,
                task_id=body.resume_task_id,
                connection=db,
            )
            if task is not None:
                db.execute(
                    """INSERT INTO executor_leases(task_id, lease_seconds) VALUES (?, ?)
                       ON CONFLICT(task_id) DO UPDATE SET lease_seconds=excluded.lease_seconds""",
                    (task.task_id, body.lease_seconds),
                )
                self._audit(db, trace_id, "lease", task.task_id, body.worker_id)
            return task

    @staticmethod
    def _task(db: Connection, task_id: str):
        row = db.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(f"任务不存在：{task_id}")
        return row

    @staticmethod
    def _owned(row, body: ExecutorReport, now: datetime):
        if (
            row["status"] != TaskStatus.RUNNING.value
            or row["lease_owner"] != body.worker_id
            or row["lease_expires_at"] is None
            or datetime.fromisoformat(row["lease_expires_at"]) < now
            or (body.attempt_count is not None and row["attempt_count"] != body.attempt_count)
        ):
            raise InvalidTransitionError("执行器没有当前有效的任务租约。")

    def heartbeat(self, task_id: str, body: ExecutorHeartbeat, trace_id: str) -> TaskRecord:
        with self.queue.database.transaction() as db:
            now = datetime.now(UTC)
            row = self._task(db, task_id)
            self._owned(row, body, now)
            lease = db.execute(
                "SELECT lease_seconds FROM executor_leases WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if lease is None:
                raise InvalidTransitionError("任务未通过执行器接口领取。")
            expires = now + timedelta(seconds=lease["lease_seconds"])
            db.execute(
                "UPDATE tasks SET lease_expires_at = ? WHERE task_id = ?",
                (expires.isoformat(), task_id),
            )
            self.queue.outbox.append_in_transaction(
                db,
                topic="executor.progress",
                trace_id=trace_id,
                payload={"task_id": task_id, **body.model_dump(mode="json")},
            )
            self._audit(db, trace_id, "heartbeat", task_id, body.worker_id)
            return self.queue._row_to_record(row)

    def report(
        self,
        task_id: str,
        body: ExecutorComplete | ExecutorFail,
        trace_id: str,
    ) -> TaskRecord:
        report_hash = canonical_hash({"type": type(body).__name__, **body.model_dump(mode="json")})
        with self.queue.database.transaction() as db:
            now = datetime.now(UTC)
            row = self._task(db, task_id)
            lease = db.execute(
                "SELECT * FROM executor_leases WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if lease is None:
                raise InvalidTransitionError("任务未通过执行器接口领取。")
            if (
                lease["report_hash"] == report_hash
                and lease["reported_attempt"] == row["attempt_count"]
            ):
                return TaskRecord.model_validate_json(lease["report_json"])
            self._owned(row, body, now)

            if isinstance(body, ExecutorComplete):
                self.store_result_in_transaction(
                    db, row, body.artifacts, body.qc, body.metrics.model_dump(mode="json"), now
                )
                target = TaskStatus.COMPLETED
                action = "complete"
                db.execute(
                    "UPDATE tasks SET error_code = NULL, error_message = NULL WHERE task_id = ?",
                    (task_id,),
                )
            else:
                target = (
                    TaskStatus.RETRYING
                    if body.retryable and row["attempt_count"] < row["max_attempts"]
                    else TaskStatus.FAILED
                )
                action = "fail"
                db.execute(
                    "UPDATE tasks SET error_code = ?, error_message = ? WHERE task_id = ?",
                    ("EXECUTOR_FAILED", body.error, task_id),
                )
            updated = self.queue.transition_in_transaction(
                db,
                task_id=task_id,
                target=target,
                reason=f"executor_{action}",
                trace_id=trace_id,
                occurred_at=now,
            )
            db.execute(
                """UPDATE executor_leases
                   SET reported_attempt = ?, report_hash = ?, report_json = ? WHERE task_id = ?""",
                (row["attempt_count"], report_hash, updated.model_dump_json(), task_id),
            )
            self._audit(db, trace_id, action, task_id, body.worker_id)
            return updated

    @staticmethod
    def store_result_in_transaction(
        db,
        row,
        entries: Sequence[ExecutorArtifact],
        qc,
        metrics,
        now: datetime,
        *,
        result_type: str = "executor",
    ) -> list[str]:
        task_id = row["task_id"]
        task_shot = json.loads(row["payload_json"]).get("shot_id")
        artifacts = []
        for artifact in entries:
            if artifact.shot_id != task_shot:
                raise InvalidTransitionError("产物 shot_id 与任务分镜不一致。")
            data = artifact.model_dump(mode="json")
            artifact_id = str(uuid4())
            db.execute(
                """INSERT INTO executor_artifacts(artifact_id, task_id, metadata_json)
                   VALUES (?, ?, ?)""",
                (artifact_id, task_id, json.dumps(data, ensure_ascii=False)),
            )
            artifacts.append({"artifact_id": artifact_id, **data})
        manifest = {
            "artifacts": artifacts,
            "qc": qc,
            "metrics": metrics,
        }
        result_id = str(uuid4())
        db.execute(
            """INSERT INTO results(result_id, project_id, task_id, result_type, object_hash,
                                   manifest_json, schema_version, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                result_id,
                row["project_id"],
                task_id,
                result_type,
                canonical_hash(manifest),
                json.dumps(manifest, ensure_ascii=False),
                "2.2.0",
                now.isoformat(),
            ),
        )
        db.execute("UPDATE tasks SET result_id = ? WHERE task_id = ?", (result_id, task_id))
        return [item["artifact_id"] for item in artifacts]

    def upload(
        self,
        task_id: str,
        body: ExecutorReport,
        jpeg: bytes,
        artifact_sha256: str | None,
        trace_id: str,
    ) -> ThumbnailRecord:
        with self.queue.database.transaction() as db:
            row = self._task(db, task_id)
            self._owned(row, body, datetime.now(UTC))
            if (
                db.execute(
                    "SELECT 1 FROM executor_leases WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
                is None
            ):
                raise InvalidTransitionError("任务未通过执行器接口领取。")
            thumbnail_id, inserted = self.store_thumbnail_in_transaction(
                db, task_id, row["attempt_count"], jpeg, artifact_sha256
            )
            if inserted:
                self._audit(db, trace_id, "thumbnail", task_id, body.worker_id)
            return ThumbnailRecord(thumbnail_id=thumbnail_id)

    @staticmethod
    def store_thumbnail_in_transaction(
        db: Connection,
        task_id: str,
        attempt: int,
        jpeg: bytes,
        artifact_sha256: str | None,
    ) -> tuple[str, bool]:
        thumbnail_id = canonical_hash(
            {
                "task": task_id,
                "attempt": attempt,
                "artifact": artifact_sha256,
                "jpeg": sha256(jpeg).hexdigest(),
            }
        )
        inserted = db.execute(
            """INSERT OR IGNORE INTO executor_thumbnails
               (thumbnail_id, task_id, attempt, artifact_sha256, jpeg)
               VALUES (?, ?, ?, ?, ?)""",
            (thumbnail_id, task_id, attempt, artifact_sha256, jpeg),
        )
        return thumbnail_id, inserted.rowcount > 0

    def thumbnail(self, task_id: str, thumbnail_id: str) -> ThumbnailContent:
        row = self.queue.database.fetchone(
            """SELECT jpeg FROM executor_thumbnails WHERE task_id = ? AND thumbnail_id = ?""",
            (task_id, thumbnail_id),
        )
        if row is None:
            raise KeyError("缩略图不存在。")
        return ThumbnailContent(
            thumbnail_id=thumbnail_id,
            jpeg_base64=base64.b64encode(
                row["jpeg"],
            ).decode("ascii"),
        )

    def artifacts(self, task_id: str) -> ArtifactList:
        with self.queue.database.transaction() as db:
            return self.artifacts_in_transaction(db, self._task(db, task_id))

    @staticmethod
    def artifacts_in_transaction(db: Connection, task) -> ArtifactList:
        task_id = task["task_id"]
        result_id = task["result_id"]
        result = db.execute(
            """SELECT manifest_json FROM results WHERE result_id = ?
               AND result_type IN ('executor', 'production_import')""",
            (result_id,),
        ).fetchone()
        dependency = db.execute(
            """SELECT depends_on_task_id FROM task_dependencies
               WHERE task_id = ? ORDER BY rowid LIMIT 1""",
            (task_id,),
        ).fetchone()
        thumbnails = {
            row["artifact_sha256"]: row["thumbnail_id"]
            for row in db.execute(
                """SELECT thumbnail_id, artifact_sha256 FROM executor_thumbnails
                   WHERE task_id = ? AND attempt = ? ORDER BY rowid""",
                (task_id, task["attempt_count"]),
            )
        }
        artifacts = []
        for row in db.execute(
            "SELECT * FROM executor_artifacts WHERE task_id = ? ORDER BY rowid",
            (task_id,),
        ):
            data = json.loads(row["metadata_json"])
            artifacts.append(
                ReviewedArtifact(
                    **data,
                    artifact_id=row["artifact_id"],
                    decision=row["decision"],
                    note=row["note"],
                    thumbnail_id=thumbnails.get(data["sha256"]),
                )
            )
        return ArtifactList(
            result_id=result_id,
            upstream_task_id=dependency["depends_on_task_id"] if dependency else None,
            artifacts=artifacts,
            sheet_thumbnail_id=thumbnails.get(None),
            qc=json.loads(result["manifest_json"])["qc"] if result else {},
        )

    def task_for_artifact(self, artifact_id: str) -> TaskRecord:
        row = self.queue.database.fetchone(
            "SELECT task_id FROM executor_artifacts WHERE artifact_id = ?",
            (artifact_id,),
        )
        if row is None:
            raise KeyError("产物不存在。")
        return self.queue.get(row["task_id"])

    def decide(
        self,
        artifact_id: str,
        body: ArtifactDecision,
        trace_id: str,
        *,
        actor_type: str = "device",
        actor_id: str = "authenticated-device",
    ) -> ReviewedArtifact:
        with self.queue.database.transaction() as db:
            artifact = db.execute(
                "SELECT * FROM executor_artifacts WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchone()
            if artifact is None:
                raise KeyError("产物不存在。")
            task = self._task(db, artifact["task_id"])
            payload = json.loads(task["payload_json"])
            kind = json.loads(artifact["metadata_json"])["kind"]
            if kind == "sheet" or task["task_type"] == "edit.assemble":
                raise InvalidTransitionError("该产物不能作为分镜候选。")
            if body.decision == "pick":
                db.execute(
                    """UPDATE executor_artifacts SET decision = NULL
                       WHERE decision = 'pick' AND artifact_id <> ?
                         AND json_extract(metadata_json, '$.kind') = ?
                         AND task_id IN (
                           SELECT task_id FROM tasks
                           WHERE json_extract(payload_json, '$.episode_id') = ?
                             AND json_extract(payload_json, '$.shot_id') = ?
                         )""",
                    (artifact_id, kind, payload["episode_id"], payload["shot_id"]),
                )
            historical = task["task_type"] == IMPORTED_TASK_TYPE
            if body.decision == "redo" and artifact["decision"] != "redo" and not historical:
                self._redo(db, task, trace_id)
            db.execute(
                "UPDATE executor_artifacts SET decision = ?, note = ? WHERE artifact_id = ?",
                (body.decision, body.note, artifact_id),
            )
            self.audit.append(
                connection=db,
                trace_id=trace_id,
                actor_type=actor_type,
                actor_id=actor_id,
                action="artifact.decision",
                resource_type="artifact",
                resource_id=artifact_id,
                decision=body.decision,
                reason_code=None,
                details={"note": body.note, "queues_generation": False}
                if historical and body.decision == "redo"
                else {"note": body.note},
            )
            self.queue.outbox.append_in_transaction(
                db,
                topic="artifact.decided",
                trace_id=trace_id,
                payload={
                    "task_id": task["task_id"],
                    "episode_id": payload["episode_id"],
                    "artifact_id": artifact_id,
                    "decision": body.decision,
                },
            )
            return next(
                item
                for item in self.artifacts_in_transaction(db, task).artifacts
                if item.artifact_id == artifact_id
            )

    def retry(self, task_id: str, trace_id: str) -> TaskRecord:
        with self.queue.database.transaction() as db:
            task = self._task(db, task_id)
            if task["status"] not in {TaskStatus.FAILED.value, TaskStatus.CANCELLED.value}:
                raise InvalidTransitionError("只有 Failed 或 Cancelled 任务可以重试。")
            new_task = self._clone(db, task, task_id, self._dependencies(db, task_id), trace_id)
            self._clone_children(db, task_id, new_task.task_id, trace_id)
            return new_task

    @staticmethod
    def _dependencies(db: Connection, task_id: str) -> tuple[str, ...]:
        return tuple(
            row["depends_on_task_id"]
            for row in db.execute(
                "SELECT depends_on_task_id FROM task_dependencies WHERE task_id = ?",
                (task_id,),
            )
        )

    def _redo(self, db: Connection, task, trace_id: str):
        new_task = self._clone(
            db,
            task,
            task["parent_task_id"],
            self._dependencies(db, task["task_id"]),
            trace_id,
        )
        db.execute(
            "INSERT INTO executor_redos(task_id, source_task_id) VALUES (?, ?)",
            (new_task.task_id, task["task_id"]),
        )
        self._clone_children(db, task["task_id"], new_task.task_id, trace_id)

    def _clone_children(self, db: Connection, source_id: str, new_id: str, trace_id: str):
        children = db.execute(
            """SELECT tasks.* FROM task_dependencies JOIN tasks USING (task_id)
               WHERE depends_on_task_id = ? AND task_id NOT IN (SELECT task_id FROM executor_redos)
               ORDER BY tasks.rowid""",
            (source_id,),
        ).fetchall()
        # Sibling redo branches share a parent. Each stage needs one downstream copy.
        copied = set()
        for child in children:
            if child["task_type"] in copied:
                continue
            copied.add(child["task_type"])
            clone = self._clone(db, child, new_id, (new_id,), trace_id)
            self._clone_children(db, child["task_id"], clone.task_id, trace_id)

    def _clone(
        self,
        db: Connection,
        task,
        parent_id: str | None,
        dependencies: tuple[str, ...],
        trace_id: str,
    ) -> TaskRecord:
        original = self.queue._row_to_record(task)
        payload = original.payload
        if original.task_type.startswith("gen."):
            payload = {**payload, "jobs": {**payload["jobs"], "out": "$bridge.output"}}
        new_task = self.queue._create_in_transaction(
            db,
            request=TaskCreate(
                task_type=original.task_type,
                payload=payload,
                priority=original.priority,
                project_id=original.project_id,
                resource_tag=original.resource_tag,
                max_attempts=original.max_attempts,
                timeout_seconds=original.timeout_seconds,
            ),
            parent_task_id=parent_id,
            trace_id=trace_id,
        )
        db.executemany(
            "INSERT INTO task_dependencies(task_id, depends_on_task_id) VALUES (?, ?)",
            ((new_task.task_id, dependency) for dependency in dependencies),
        )
        return new_task

    def _audit(self, db: Connection, trace_id: str, action: str, task_id: str, worker_id: str):
        self.audit.append(
            connection=db,
            trace_id=trace_id,
            actor_type="windows_device",
            actor_id=worker_id,
            action=f"executor.{action}",
            resource_type="task",
            resource_id=task_id,
            decision="allow",
            reason_code=None,
            details={},
        )
