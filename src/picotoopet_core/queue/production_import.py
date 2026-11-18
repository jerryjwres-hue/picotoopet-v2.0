"""原子登记外部已生成的媒体，保留现有审片决定。"""

import json
import ntpath
from datetime import UTC, datetime
from sqlite3 import Connection
from uuid import NAMESPACE_OID, uuid5

from picotoopet_core.audit.writer import canonical_hash
from picotoopet_core.domain.enums import TaskStatus
from picotoopet_core.domain.episode import Episode
from picotoopet_core.domain.executor import IMPORTED_TASK_TYPE
from picotoopet_core.domain.history_import import (
    EpisodeHistoryImport,
    EpisodeHistoryImported,
    HistoricalCandidate,
)
from picotoopet_core.queue.executor import ExecutorService
from picotoopet_core.queue.state_machine import InvalidTransitionError

_IMPORT_NAMESPACE = uuid5(NAMESPACE_OID, "picotoopet.production.history.v1")


def _preserve_selection(
    db: Connection,
    episode_id: str,
    item: HistoricalCandidate,
) -> str | None:
    if item.decision != "pick":
        return item.decision
    existing = db.execute(
        """SELECT 1 FROM executor_artifacts a JOIN tasks t USING (task_id)
           WHERE a.decision = 'pick' AND json_extract(a.metadata_json, '$.kind') = ?
             AND json_extract(t.payload_json, '$.episode_id') = ?
             AND json_extract(t.payload_json, '$.shot_id') = ?
           LIMIT 1""",
        (item.kind, episode_id, item.shot_id),
    ).fetchone()
    return None if existing else "pick"


def _record_review(
    executor: ExecutorService,
    db: Connection,
    artifact_id: str,
    decision: str | None,
    note: str,
    trace_id: str,
    *,
    reason_code: str,
) -> None:
    db.execute(
        "UPDATE executor_artifacts SET decision = ?, note = ? WHERE artifact_id = ?",
        (decision, note, artifact_id),
    )
    executor.audit.append(
        connection=db,
        trace_id=trace_id,
        actor_type="device",
        actor_id="authenticated-device",
        action="artifact.decision" if decision is not None else "artifact.note",
        resource_type="artifact",
        resource_id=artifact_id,
        decision=decision if decision is not None else "allow",
        reason_code=reason_code,
        details={"note": note},
    )


def _fill_offline_review(executor, db, episode_id, prior, item, trace_id):
    if item.decision is None and not item.note.strip():
        return "unchanged"
    if item.note == prior["note"] and (item.decision is None or item.decision == prior["decision"]):
        return "unchanged"
    if prior["decision"] is not None or prior["note"]:
        return "conflict"
    # 选用被另一条候选替换时，当前 decision 会清空，审计仍保留旧决定。
    reviewed_before = db.execute(
        """SELECT 1 FROM audit_events WHERE action IN ('artifact.decision', 'artifact.note')
           AND resource_type = 'artifact' AND resource_id = ? LIMIT 1""",
        (prior["artifact_id"],),
    ).fetchone()
    if reviewed_before or (
        item.decision == "pick" and _preserve_selection(db, episode_id, item) is None
    ):
        return "conflict"
    _record_review(
        executor,
        db,
        prior["artifact_id"],
        item.decision,
        item.note,
        trace_id,
        reason_code="HISTORICAL_IMPORT_FILL",
    )
    return "updated"


def import_episode_history(
    executor: ExecutorService,
    body: EpisodeHistoryImport,
    previews: list[bytes | None],
    trace_id: str,
) -> EpisodeHistoryImported:
    episode = body.episode
    episode_id = episode.episode_id
    inserted = 0
    updated = 0
    conflicts = 0
    with executor.queue.database.transaction() as db:
        existing = db.execute(
            "SELECT spec_json FROM production_episodes WHERE episode_id = ?", (episode_id,)
        ).fetchone()
        if existing is None:
            db.execute(
                "INSERT INTO production_episodes (episode_id, spec_json) VALUES (?, ?)",
                (episode_id, episode.model_dump_json()),
            )
        elif Episode.model_validate_json(existing["spec_json"]) != episode:
            raise InvalidTransitionError("episode_id 已存在，且内容不同。")

        for item, jpeg in zip(body.candidates, previews, strict=True):
            key = canonical_hash(
                {
                    "episode_id": episode_id,
                    "shot_id": item.shot_id,
                    "kind": item.kind,
                    "take": item.take,
                    "path": ntpath.normcase(ntpath.normpath(item.path)),
                }
            )
            task_id = str(uuid5(_IMPORT_NAMESPACE, key))
            prior = db.execute(
                """SELECT json_extract(a.metadata_json, '$.sha256') AS digest,
                          json_extract(a.metadata_json, '$.bytes') AS length,
                          json_extract(a.metadata_json, '$.seed') AS seed,
                          json_extract(a.metadata_json, '$.source_id') AS source_id,
                          a.artifact_id, a.decision, a.note
                   FROM tasks t LEFT JOIN executor_artifacts a USING (task_id)
                   WHERE t.task_id = ?""",
                (task_id,),
            ).fetchone()
            if prior is not None:
                if prior["digest"] != item.sha256 or prior["length"] != item.bytes:
                    raise InvalidTransitionError(
                        "历史候选路径的内容已变化，请使用保留原文件的版本路径。"
                    )
                if any(
                    old is not None and new is not None and old != new
                    for old, new in (
                        (prior["seed"], item.seed),
                        (prior["source_id"], item.source_id),
                    )
                ):
                    raise InvalidTransitionError("历史候选的 seed 或来源标识与现有记录冲突。")
                if body.fill_unreviewed:
                    outcome = _fill_offline_review(executor, db, episode_id, prior, item, trace_id)
                    updated += outcome == "updated"
                    conflicts += outcome == "conflict"
                continue

            now = datetime.now(UTC)
            payload = {
                "episode_id": episode_id,
                "shot_id": item.shot_id,
                "source": "historical_import",
                "episode_metadata_complete": body.episode_metadata_complete,
            }
            # 历史记录出生即为已完成。没有队列、领取、尝试或合成的状态事件。
            db.execute(
                """INSERT INTO tasks (
                       task_id, task_type, status, payload_json,
                       created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    task_id,
                    IMPORTED_TASK_TYPE,
                    TaskStatus.COMPLETED.value,
                    json.dumps(payload, ensure_ascii=False),
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            task = executor._task(db, task_id)
            (artifact_id,) = executor.store_result_in_transaction(
                db, task, [item.artifact()], item.qc, {}, now, result_type="production_import"
            )
            if jpeg is not None:
                executor.store_thumbnail_in_transaction(db, task_id, 0, jpeg, item.sha256)

            decision = _preserve_selection(db, episode_id, item)
            if body.fill_unreviewed and item.decision == "pick" and decision is None:
                conflicts += 1
            if decision is not None or item.note:
                _record_review(
                    executor,
                    db,
                    artifact_id,
                    decision,
                    item.note,
                    trace_id,
                    reason_code="HISTORICAL_IMPORT",
                )
            inserted += 1

        existing_count = len(body.candidates) - inserted
        if inserted or updated:
            executor.audit.append(
                connection=db,
                trace_id=trace_id,
                actor_type="device",
                actor_id="authenticated-device",
                action="episode.import",
                resource_type="episode",
                resource_id=episode_id,
                decision="allow",
                reason_code=None,
                details={
                    "inserted_count": inserted,
                    "existing_count": existing_count,
                    "episode_metadata_complete": body.episode_metadata_complete,
                    "updated_count": updated,
                    "conflict_count": conflicts,
                },
            )
            executor.queue.outbox.append_in_transaction(
                db,
                topic="episode.imported",
                payload={
                    "episode_id": episode_id,
                    "inserted_count": inserted,
                    "updated_count": updated,
                },
                trace_id=trace_id,
            )
    return EpisodeHistoryImported(
        episode_id=episode_id,
        inserted_count=inserted,
        existing_count=existing_count,
        updated_count=updated or None,
        conflict_count=conflicts or None,
    )
