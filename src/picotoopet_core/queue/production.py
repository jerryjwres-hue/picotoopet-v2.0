"""生产任务链、分镜审片汇总与合成入队。"""

from __future__ import annotations

import json
from collections import defaultdict
from sqlite3 import Connection

from picotoopet_core.audit.writer import canonical_hash
from picotoopet_core.domain.enums import TaskStatus
from picotoopet_core.domain.episode import (
    Episode,
    EpisodeCreated,
    EpisodeReview,
    EpisodeSummary,
    ReviewCandidate,
    Shot,
    ShotReview,
)
from picotoopet_core.domain.executor import (
    GPU_TAG,
    IMPORTED_TASK_TYPE,
    TASK_RUNNERS,
    ExecutorPayload,
)
from picotoopet_core.domain.models import TaskCreate, TaskRecord
from picotoopet_core.queue.executor import ExecutorService
from picotoopet_core.queue.state_machine import InvalidTransitionError

SHOT_TYPES = ("gen.keyframe", "gen.video", "gen.foley")


def _shot_jobs(episode: Episode, shot: Shot):
    frames = []
    for label, frame in (("first", shot.first_frame), ("last", shot.last_frame)):
        if frame is not None:
            frames.append(
                {
                    "id": f"{shot.shot_id}_{label}",
                    "refs": frame.refs,
                    "prompt": frame.prompt,
                    "seeds": shot.video.seeds[:1],
                }
            )
    width, height = episode.edit.size
    video = {
        "id": shot.shot_id,
        **shot.video.model_dump(),
        "seconds": shot.seconds,
        "w": width,
        "h": height,
        "first": "$parent.first",
    }
    if shot.last_frame:
        video["last"] = "$parent.last"
    foley = "；".join(
        item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
        for item in shot.audio.foley
    )
    return (
        {"out": "$bridge.output", "jobs": frames},
        {"out": "$bridge.output", "jobs": [video]},
        {
            "out": "$bridge.output",
            "jobs": [
                {
                    "id": shot.shot_id,
                    "video": "$parent.video",
                    "prompt": foley,
                    "seeds": shot.video.seeds[:1],
                }
            ],
            "vocal_from": shot.audio.vocal_from,
        },
    )


class ProductionService:
    def __init__(self, executor: ExecutorService):
        self.executor = executor
        self.queue = executor.queue

    def create(self, episode: Episode, trace_id: str) -> tuple[EpisodeCreated, bool]:
        with self.queue.database.transaction() as db:
            existing = db.execute(
                "SELECT spec_json FROM production_episodes WHERE episode_id = ?",
                (episode.episode_id,),
            ).fetchone()
            if existing:
                if Episode.model_validate_json(existing["spec_json"]) != episode:
                    raise InvalidTransitionError("episode_id 已存在，且内容不同。")
                rows = self._tasks(db, episode.episode_id)
                return EpisodeCreated(
                    episode=episode,
                    tasks=[self.queue._row_to_record(row) for row in rows],
                ), False
            db.execute(
                "INSERT INTO production_episodes(episode_id, spec_json) VALUES (?, ?)",
                (episode.episode_id, episode.model_dump_json()),
            )
            tasks = []
            for shot in episode.shots:
                parent = None
                for task_type, jobs in zip(SHOT_TYPES, _shot_jobs(episode, shot), strict=True):
                    task = self.queue._create_in_transaction(
                        db,
                        request=TaskCreate(
                            task_type=task_type,
                            resource_tag=GPU_TAG,
                            payload=ExecutorPayload(
                                episode_id=episode.episode_id,
                                shot_id=shot.shot_id,
                                runner=TASK_RUNNERS[task_type],
                                jobs=jobs,
                            ).model_dump(mode="json"),
                        ),
                        parent_task_id=parent,
                        trace_id=trace_id,
                    )
                    if parent:
                        db.execute(
                            "INSERT INTO task_dependencies(task_id, depends_on_task_id) "
                            "VALUES (?, ?)",
                            (task.task_id, parent),
                        )
                    parent = task.task_id
                    tasks.append(task)
            self.executor.audit.append(
                connection=db,
                trace_id=trace_id,
                actor_type="device",
                actor_id="authenticated-device",
                action="episode.create",
                resource_type="episode",
                resource_id=episode.episode_id,
                decision="allow",
                reason_code=None,
                details={"shot_count": len(episode.shots)},
            )
            return EpisodeCreated(episode=episode, tasks=tasks), True

    def list(self) -> list[EpisodeSummary]:
        return [
            EpisodeSummary(episode_id=row["episode_id"], title=row["title"])
            for row in self.queue.database.fetchall(
                """SELECT episode_id, json_extract(spec_json, '$.title') AS title
                   FROM production_episodes ORDER BY rowid DESC""",
            )
        ]

    @staticmethod
    def _episode(db: Connection, episode_id: str) -> Episode:
        row = db.execute(
            "SELECT spec_json FROM production_episodes WHERE episode_id = ?",
            (episode_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"剧集不存在：{episode_id}")
        return Episode.model_validate_json(row["spec_json"])

    @staticmethod
    def _tasks(db: Connection, episode_id: str, *, include_history: bool = False):
        return db.execute(
            """SELECT tasks.*, redos.task_id IS NOT NULL AS is_redo,
                      redos.source_task_id AS redo_source
               FROM tasks LEFT JOIN executor_redos AS redos USING (task_id)
               WHERE json_extract(payload_json, '$.episode_id') = ?
                 AND (task_type IN ('gen.keyframe', 'gen.video', 'gen.foley', 'qc.check')
                      OR (? AND task_type = ?))
               ORDER BY tasks.rowid""",
            (episode_id, include_history, IMPORTED_TASK_TYPE),
        ).fetchall()

    def review(self, episode_id: str) -> EpisodeReview:
        with self.queue.database.transaction() as db:
            return self._review(db, self._episode(db, episode_id))

    def _review(self, db: Connection, episode: Episode) -> EpisodeReview:
        grouped = defaultdict(list)
        task_rows = self._tasks(db, episode.episode_id, include_history=True)
        historical_only = all(row["task_type"] == IMPORTED_TASK_TYPE for row in task_rows)
        for row in task_rows:
            grouped[json.loads(row["payload_json"])["shot_id"]].append(row)
        shots = []
        for shot in episode.shots:
            rows = grouped[shot.shot_id]
            candidates = []
            qc_by_hash = {}
            gates = {}
            manual = False
            lists = [(row, self.executor.artifacts_in_transaction(db, row)) for row in rows]
            for row, result in lists:
                if row["task_type"] == "qc.check":
                    jobs = json.loads(row["payload_json"])["jobs"]
                    if source_id := jobs.get("source_task_id"):
                        reports = {
                            thumb["artifact_sha256"]: thumb["thumbnail_id"]
                            for thumb in db.execute(
                                """SELECT artifact_sha256,thumbnail_id FROM executor_thumbnails
                                   WHERE task_id=? AND attempt=? ORDER BY rowid""",
                                (row["task_id"], row["attempt_count"]),
                            )
                        }
                        confirmed = {
                            pick["artifact_id"]: bool(pick["released"])
                            for pick in db.execute(
                                """SELECT artifact_id,released FROM executor_qc_picks
                                   WHERE gate_id=?""",
                                (row["task_id"],),
                            )
                        }
                        superseded = any(item["redo_source"] == source_id for item in rows)
                        gates[source_id] = (row, result, reports, confirmed, superseded)
                        if row["error_code"] == "QC_MANUAL_REVIEW":
                            manual |= not superseded and not any(confirmed.values())
                        continue
                    checks = result.qc.get("by_sha256")
                    if isinstance(checks, dict):
                        qc_by_hash.update(
                            (digest, check)
                            for digest, check in checks.items()
                            if isinstance(check, dict)
                        )
            for row, result in lists:
                for item in result.artifacts:
                    if item.kind == "sheet":
                        continue
                    qc = qc_by_hash.get(item.sha256, result.qc)
                    if gate := gates.get(row["task_id"]):
                        check, report, reports, confirmed, superseded = gate
                        qc = {
                            **report.qc.get("by_sha256", {}).get(item.sha256, {}),
                            "gate_status": check["error_code"] or check["status"],
                            "report_task_id": check["task_id"],
                            "report_thumbnail_id": reports.get(
                                item.sha256, report.sheet_thumbnail_id
                            ),
                        }
                        if check["error_code"] == "QC_MANUAL_REVIEW":
                            qc["can_confirm"] = (
                                not superseded
                                and (not any(confirmed.values()) or item.artifact_id in confirmed)
                                and item.kind in ("image", "video")
                            )
                            qc["can_redo"] = not superseded
                            qc["human_confirmed"] = item.artifact_id in confirmed
                            qc["human_released"] = any(confirmed.values())
                    candidates.append(
                        ReviewCandidate(
                            **item.model_dump(),
                            task_id=row["task_id"],
                            task_type=row["task_type"],
                            sheet_thumbnail_id=result.sheet_thumbnail_id,
                            qc=qc,
                        )
                    )
            statuses = {row["status"] for row in rows}
            if self._picked_video(candidates):
                status = "已选用"
            elif manual:
                status = "待人工复核"
            elif TaskStatus.RUNNING.value in statuses:
                status = "执行中"
            elif TaskStatus.RETRYING.value in statuses:
                status = "等待重试"
            elif candidates:
                status = "待审片"
            elif TaskStatus.FAILED.value in statuses:
                status = "执行失败"
            elif TaskStatus.CANCELLED.value in statuses:
                status = "已取消"
            else:
                status = "待导入" if not rows and historical_only else "排队中"
            shots.append(
                ShotReview(
                    shot_id=shot.shot_id,
                    status=status,
                    candidates=candidates,
                    redo_count=sum(row["is_redo"] for row in rows),
                )
            )
        return EpisodeReview(
            shots=shots, can_assemble=all(self._picked_video(shot.candidates) for shot in shots)
        )

    @staticmethod
    def _picked_video(candidates: list[ReviewCandidate]) -> ReviewCandidate | None:
        return next(
            (item for item in candidates if item.kind == "video" and item.decision == "pick"), None
        )

    def assemble(self, episode_id: str, trace_id: str) -> TaskRecord:
        with self.queue.database.transaction() as db:
            episode = self._episode(db, episode_id)
            review = self._review(db, episode)
            if not review.can_assemble:
                raise InvalidTransitionError("请先为每个分镜选用一个视频。")
            inputs = []
            for shot, reviewed in zip(episode.shots, review.shots, strict=True):
                picked = self._picked_video(reviewed.candidates)
                assert picked is not None
                foley_tracks = []
                source = self.executor.artifacts_in_transaction(
                    db, self.executor._task(db, picked.task_id)
                )
                single_video = sum(item.kind == "video" for item in source.artifacts) == 1
                for child in db.execute(
                    """SELECT * FROM tasks WHERE parent_task_id=? AND task_type='gen.foley'
                       AND status='Completed' ORDER BY rowid DESC""",
                    (picked.task_id,),
                ):
                    audio = self.executor.artifacts_in_transaction(db, child)
                    sources = audio.qc.get("foley_by_sha256", {})
                    if not isinstance(sources, dict):
                        continue
                    foley_tracks = [
                        {"file": a.path, "sha256": a.sha256}
                        for a in audio.artifacts
                        if a.kind == "audio"
                        and a.shot_id == shot.shot_id
                        and (
                            sources.get(a.sha256) == picked.sha256
                            or (not sources and single_video and a.take == picked.take)
                        )
                    ]
                    if foley_tracks:
                        break
                inputs.append(
                    {
                        "path": picked.path,
                        "foley_tracks": foley_tracks,
                        "sha256": picked.sha256,
                        "artifact_id": picked.artifact_id,
                        "shot_id": shot.shot_id,
                        "seconds": shot.seconds,
                        "caption": shot.caption,
                        "audio": shot.audio.model_dump(mode="json"),
                        "transition_out": shot.transition_out.model_dump(mode="json"),
                    }
                )
            jobs = {"shots": inputs, "edit": episode.edit.model_dump(mode="json")}
            task = self.queue._create_in_transaction(
                db,
                request=TaskCreate(
                    task_type="edit.assemble",
                    resource_tag=GPU_TAG,
                    idempotency_key=f"assemble:{episode_id}:{canonical_hash(jobs)}",
                    payload=ExecutorPayload(
                        episode_id=episode_id,
                        shot_id="episode",
                        runner=TASK_RUNNERS["edit.assemble"],
                        jobs=jobs,
                    ).model_dump(mode="json"),
                ),
                trace_id=trace_id,
            )
            self.executor.audit.append(
                connection=db,
                trace_id=trace_id,
                actor_type="device",
                actor_id="authenticated-device",
                action="episode.assemble",
                resource_type="episode",
                resource_id=episode_id,
                decision="allow",
                reason_code=None,
                details={"task_id": task.task_id},
            )
            return task
