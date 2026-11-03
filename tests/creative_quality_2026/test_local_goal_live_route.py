"""Offline integration: the real GoalLocalCreativeCoordinator.handler routes new 3-shot Goals to v2.

Real handler, real CreativeIntelligenceService, real SQLite, real Creative coordinator over a
scripted Ollama transport. Only the Goal/Workflow/ResultStore facts and the model JSON are faked.
Nothing here starts a model, a GPU, or looks at a picture.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
import story_fixture_2026 as fx
from director_fixtures import (
    EVIDENCE,
    V1,
    V2,
    OllamaDouble,
    Runtime,
    open_runtime,
    stage_outputs,
)

from picotoopet_core.autonomous.human_pipeline import (
    _DISCOVERY_RESULT_TYPE,
    _DISCOVERY_STEP,
    _LOCAL_CREATIVE_RESULT_TYPE,
    _SYNTHESIS_RESULT_TYPE,
    _SYNTHESIS_STEP,
)
from picotoopet_core.autonomous.local_creative import GoalLocalCreativeCoordinator
from picotoopet_core.autonomous.models import GoalCreate, GoalOrigin, PriorityClass
from picotoopet_core.autonomous.repository import AutonomousGoalRepository
from picotoopet_core.creative.director import STORY_GATE_RULES
from picotoopet_core.creative.execution import CreativeIntelligenceCoordinator
from picotoopet_core.creative.repository import CreativeRepository
from picotoopet_core.creative.service import CreativeIntelligenceService
from picotoopet_core.creative.source import CreativeSourceNormalizer
from picotoopet_core.creative.store import CreativeArtifactStore
from picotoopet_core.db.database import Database
from picotoopet_core.domain.models import TaskRecord, TaskStatus
from picotoopet_core.queue.diagnostic_repository import DiagnosticQueueRepository

THREE_SHOT = (
    "Exactly 3 shots, text-to-video only: no reference image. Each shot 4.0 seconds, total "
    "12 seconds, landscape. A white cat gets a clip-on tag: hook, demo, payoff."
)
ORDINARY = "Create a short product education video."


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


class _GoalFacts:
    """Real durable Goal row; Workflow and ResultStore facts are in-memory (no Core queue needed)."""

    def __init__(self, rt: Runtime, objective: str) -> None:
        self.goal_id = AutonomousGoalRepository(rt.database).create(GoalCreate(
            origin=GoalOrigin.HUMAN, intent_type="video.creative", priority_class=PriorityClass.P1,
            objective=objective, constraints={"local_video_preferred": True},
            idempotency_key=f"live-route-{uuid4()}",
        )).goal_id
        AutonomousGoalRepository(rt.database).bind_workflow(self.goal_id, "wf-1")
        self.documents = {
            _sha("discovery"): {
                "connected_evidence": [
                    {"evidence_id": EVIDENCE, "text_excerpt": "Owners like clip-on tags."}
                ],
            },
            _sha("synthesis"): {
                "goal_id": self.goal_id, "evidence_ids": [EVIDENCE],
                "findings": ["Clip-on speed is the main purchase driver."],
            },
        }
        steps = [
            SimpleNamespace(step_key=_DISCOVERY_STEP, task_id="t-discovery"),
            SimpleNamespace(step_key=_SYNTHESIS_STEP, task_id="t-synthesis"),
        ]
        records = {
            "t-discovery": SimpleNamespace(
                result_type=_DISCOVERY_RESULT_TYPE, object_hash=_sha("discovery")),
            "t-synthesis": SimpleNamespace(
                result_type=_SYNTHESIS_RESULT_TYPE, object_hash=_sha("synthesis")),
        }
        self.workflows = SimpleNamespace(get_workflow=lambda _id: SimpleNamespace(steps=steps))
        self.result_records = SimpleNamespace(get_for_task=lambda task_id: records[task_id])
        self.result_store = SimpleNamespace(
            read_json=lambda object_hash, *, max_bytes: self.documents[object_hash]
        )

    def coordinator(self, rt: Runtime) -> GoalLocalCreativeCoordinator:
        return GoalLocalCreativeCoordinator(
            goals=AutonomousGoalRepository(rt.database), workflows=self.workflows,
            result_records=self.result_records, result_store=self.result_store,
            creative=rt.service,
        )

    def task(self) -> TaskRecord:
        now = datetime.now(UTC)
        return TaskRecord(
            task_id="goal-creative-task", task_type=_LOCAL_CREATIVE_RESULT_TYPE,
            status=TaskStatus.RUNNING, priority=0, payload={"goal_id": self.goal_id},
            attempt_count=1, max_attempts=3, timeout_seconds=60, created_at=now, updated_at=now,
        )

    def rows(self, rt: Runtime) -> list[dict]:
        return [
            dict(row) for row in rt.database.fetchall(
                "SELECT creative_job_id, creative_profile FROM creative_jobs "
                "WHERE idempotency_key=?", (f"goal-video:{self.goal_id}",),
            )
        ]


def _reopen(rt: Runtime) -> Runtime:
    """Simulate an app restart: close SQLite and rebuild every service over the same file."""

    path = rt.database.path
    paths = rt.store.paths
    rt.database.close()
    database = Database(path)
    database.open()
    database.apply_migrations()
    repository = CreativeRepository(database)
    queue = DiagnosticQueueRepository(database)
    source = CreativeSourceNormalizer(database)
    store = CreativeArtifactStore(paths)
    service = CreativeIntelligenceService(
        repository=repository, source_normalizer=source, store=store, queue=queue
    )
    return Runtime(database, service, repository, queue, source, store, rt.result_id)


def _creative_task(rt: Runtime, job_id: str):  # type: ignore[no-untyped-def]
    return next(
        item for item in rt.queue.list(limit=50) if item.resource_tag == f"creative:{job_id}"
    )


def _v1_outputs(ref: str) -> list[dict]:
    parts = stage_outputs(ref)
    shots = {
        "schema_version": "1.0", "creative_profile": V1, "warnings": [],
        "needs_deep_ai": False, "needs_human": False,
        "shots": [
            {"shot_id": f"shot-{i:03d}", "beat_id": f"beat-{i:03d}", "order": i,
             "duration_seconds": 4.0, "subject": "Mochi the white cat", "environment": "room",
             "action": action, "framing": "medium shot", "lighting_style": "warm light",
             "continuity_keys": ["white cat Mochi", "teal scarf"], "required_facts": [],
             "source_evidence_ids": [], "text_reference": None,
             "production_notes": "renderer-neutral", "render_intent": "GENERATIVE_VIDEO"}
            for i, action in (
                (1, "Mochi taps the tag with her paw"),
                (2, "a hand clips the tag onto the scarf"),
                (3, "Mochi trots past the lamp"),
            )
        ],
    }
    return [parts["idea"], {**fx.brief(), "required_source_finding_refs": [ref]}, fx.script(),
            shots]


def _v2_outputs(ref: str) -> list[dict]:
    return [stage_outputs(ref)["idea"], {**fx.brief(), "required_source_finding_refs": [ref]},
            fx.script(), fx.bible()]


@pytest.fixture
def runtime(tmp_path):  # type: ignore[no-untyped-def]
    rt = open_runtime(tmp_path)
    yield rt
    rt.database.close()


def test_fresh_three_shot_goal_handler_creates_v2_job_and_enters_video_bible(
    runtime: Runtime,
) -> None:
    facts = _GoalFacts(runtime, THREE_SHOT)
    result = facts.coordinator(runtime).handler(facts.task())

    job_id = result.summary["creative_job_id"]
    assert result.result_type == _LOCAL_CREATIVE_RESULT_TYPE
    assert result.result_document["web_gpt_required"] is False
    assert facts.rows(runtime) == [{"creative_job_id": job_id, "creative_profile": V2}]
    assert runtime.repository.get_job(job_id).creative_profile == V2

    # The queued Creative task is the real one: running it reaches Video Bible and the Story Gate.
    ref = runtime.source_ref_for(job_id)
    assert ref.startswith("goal-synthesis:")
    double = OllamaDouble(_v2_outputs(ref))
    done = CreativeIntelligenceCoordinator(
        database=runtime.database, queue=runtime.queue, repository=runtime.repository,
        source_normalizer=runtime.source, store=runtime.store, adapter=double.adapter,
        configured_model_id="gpt-oss:20b",
    ).handler(_creative_task(runtime, job_id))
    assert done.summary["status"] == "creative_ready" and len(double.requests) == 4
    constraints = double.data(3)["director_constraints"]
    # Default exact-3-shot Goal (no explicit phrase) carries the default Story Gate rules.
    assert constraints["story_quality_rules"] == STORY_GATE_RULES
    assert "story_gate" not in constraints
    package = runtime.service.get_package(job_id)
    assert package is not None
    stages = package.manifest["stage_results"]
    assert "video_bible.v1" in stages and "keyframe_kit.v1" in stages


def test_ordinary_goal_handler_keeps_v1_and_has_no_video_bible(runtime: Runtime) -> None:
    facts = _GoalFacts(runtime, ORDINARY)
    result = facts.coordinator(runtime).handler(facts.task())
    job_id = result.summary["creative_job_id"]
    assert facts.rows(runtime) == [{"creative_job_id": job_id, "creative_profile": V1}]

    ref = runtime.source_ref_for(job_id)
    double = OllamaDouble(_v1_outputs(ref))
    CreativeIntelligenceCoordinator(
        database=runtime.database, queue=runtime.queue, repository=runtime.repository,
        source_normalizer=runtime.source, store=runtime.store, adapter=double.adapter,
        configured_model_id="gpt-oss:20b",
    ).handler(_creative_task(runtime, job_id))
    package = runtime.service.get_package(job_id)
    assert package is not None
    assert "video_bible.v1" not in package.manifest["stage_results"]


@pytest.mark.parametrize("persisted_profile", [V1, V2])
def test_restart_replays_persisted_job_without_reprofiling(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch, persisted_profile: str
) -> None:
    facts = _GoalFacts(runtime, THREE_SHOT)

    # Pre-fix history: the Goal's job was created under the profile that was then persisted.
    monkeypatch.setattr(
        GoalLocalCreativeCoordinator, "_profile_for_goal", lambda self, goal: persisted_profile
    )
    first = facts.coordinator(runtime).handler(facts.task())
    job_id = first.summary["creative_job_id"]
    assert facts.rows(runtime) == [{"creative_job_id": job_id, "creative_profile": persisted_profile}]
    monkeypatch.undo()

    # Restart: fresh SQLite connection and services, the real profile selector, same Goal.
    restarted = _reopen(runtime)
    try:
        second = facts.coordinator(restarted).handler(facts.task())
        assert second.summary["creative_job_id"] == job_id
        assert second.result_document["source_set_digest"] == first.result_document[
            "source_set_digest"]
        assert facts.rows(restarted) == [
            {"creative_job_id": job_id, "creative_profile": persisted_profile}
        ]
        assert restarted.repository.get_job(job_id).creative_profile == persisted_profile
        assert sum(
            1 for item in restarted.queue.list(limit=50)
            if item.resource_tag == f"creative:{job_id}"
        ) == 1

        # The survivor still runs through its own original stage list.
        ref = restarted.source_ref_for(job_id)
        outputs = _v2_outputs(ref) if persisted_profile == V2 else _v1_outputs(ref)
        double = OllamaDouble(outputs)
        CreativeIntelligenceCoordinator(
            database=restarted.database, queue=restarted.queue, repository=restarted.repository,
            source_normalizer=restarted.source, store=restarted.store, adapter=double.adapter,
            configured_model_id="gpt-oss:20b",
        ).handler(_creative_task(restarted, job_id))
        package = restarted.service.get_package(job_id)
        assert package is not None
        has_bible = "video_bible.v1" in package.manifest["stage_results"]
        assert has_bible is (persisted_profile == V2)
    finally:
        restarted.database.close()
        runtime.database = restarted.database  # fixture closes an already-closed handle safely
