"""P0 Goal local continuation: canonical task identity, source lineage and no WebGPT gate."""

from types import SimpleNamespace

import pytest

from picotoopet_core.autonomous.goal_service import HumanGoalRequest, HumanGoalType
from picotoopet_core.autonomous.video_continuation import (
    GoalVideoContinuationService,
    GoalVideoContinuationStateError,
)
from picotoopet_core.creative.models import CreativeQualityOutcome


class Sources:
    def __init__(self):
        self.ids = ["verified-result-1"]
        self.fail = False

    def load_persisted_source_set(self, creative_job_id):
        assert creative_job_id == "creative-persisted"
        if self.fail:
            return SimpleNamespace(result_package_ids=["foreign-result"])
        return SimpleNamespace(result_package_ids=self.ids)


class Creative:
    def __init__(self):
        self.calls = []
        self.source_normalizer = Sources()
        self.package_ready = False

    def create_job(self, **kwargs):
        self.calls.append(kwargs)
        assert kwargs["source_result_package_ids"] == ["verified-result-1"]
        assert kwargs["idempotency_key"] == "goal-video:g-1"
        assert kwargs["creative_profile"] == "creative.content_plan.v1"
        return SimpleNamespace(creative_job_id="creative-persisted")

    def get_package(self, creative_job_id):
        assert creative_job_id == "creative-persisted"
        if not self.package_ready:
            return None
        return SimpleNamespace(
            creative_package_id="creative-package-1",
            package_digest="c" * 64,
            quality_outcome=CreativeQualityOutcome.PASS,
        )


class Database:
    def __init__(self, creative):
        self.creative = creative

    def fetchone(self, sql, params):
        if "FROM creative_jobs" in sql:
            return {
                "creative_job_id": "creative-persisted",
                "creative_package_id": "creative-package-1" if self.creative.package_ready else None,
                "status": "CreativeReady" if self.creative.package_ready else "Queued",
            }
        raise AssertionError(sql)


class Production:
    def __init__(self):
        self.calls = []

    def create_job(self, request):
        self.calls.append(request)
        assert request.creative_package_id == "creative-package-1"
        assert request.idempotency_key == "goal-video:g-1"
        return SimpleNamespace(production_job_id="production-persisted",
                               status=SimpleNamespace(value="Ready"))


class Goals:
    def __init__(self):
        self.source_ids = ["verified-result-1"]
        self.mode = True

    def get(self, goal_id):
        assert goal_id == "g-1"
        return SimpleNamespace(
            goal_id="g-1", workflow_id="workflow-1",
            intent_type="video.creative", objective="Create a sourced video",
            constraints={"local_video_preferred": self.mode,
                         "source_result_package_ids": self.source_ids},
        )


class Workflows:
    def get_workflow(self, workflow_id):
        assert workflow_id == "workflow-1"
        return SimpleNamespace(steps=[
            SimpleNamespace(step_key="research-evidence", task_id="discovery-task"),
            SimpleNamespace(step_key="evidence-synthesis", task_id="synthesis-task"),
        ])


class Records:
    def __init__(self):
        self.ready = True

    def get_for_task(self, task_id):
        if not self.ready and task_id == "synthesis-task":
            raise KeyError("not ready")
        return SimpleNamespace(
            result_type=("autonomous.discovery.v1" if task_id == "discovery-task"
                         else "autonomous.goal_synthesis.v1"),
            object_hash=("a" if task_id == "discovery-task" else "b") * 64,
        )


class Results:
    def __init__(self):
        self.bad_binding = False

    def read_json(self, object_hash, *, max_bytes):
        assert max_bytes == 256 * 1024
        if object_hash == "a" * 64:
            return {"evidence_ids": ["real-evidence"]}
        return {
            "schema_version": "1.0",
            "goal_id": "other-goal" if self.bad_binding else "g-1",
            "evidence_ids": ["real-evidence"],
        }


def make_service():
    creative, production, goals, records, results = (
        Creative(), Production(), Goals(), Records(), Results()
    )
    return (GoalVideoContinuationService(
        database=Database(creative), handoffs=SimpleNamespace(),
        creative=creative, production=production,
        goals=goals, workflows=Workflows(),
        result_records=records, result_store=results,
    ), creative, production, goals, records, results)


def test_local_video_starts_canonical_creative_and_promotes_real_ready_package():
    service, creative, production, _, _, _ = make_service()
    waiting = service.status("g-1")
    assert waiting.continuation_mode == "local"
    assert waiting.handoff_sha256 == "a" * 64
    assert waiting.return_sha256 == "b" * 64
    assert waiting.creative_job_id == "creative-persisted"
    assert waiting.creative_package_id is None
    assert waiting.production_job_id is None
    assert production.calls == []
    creative.package_ready = True
    ready = service.status("g-1")
    assert ready.creative_package_id == "creative-package-1"
    assert ready.creative_package_digest == "c" * 64
    assert ready.production_job_id == "production-persisted"
    assert ready.production_status == "Ready"
    assert service.status("g-1").production_job_id == ready.production_job_id
    assert all(call["idempotency_key"] == "goal-video:g-1" for call in creative.calls)
    assert all(call.idempotency_key == "goal-video:g-1" for call in production.calls)


def test_local_goal_waits_for_durable_synthesis_without_issuing_creative_task():
    service, creative, _, _, records, _ = make_service()
    records.ready = False
    with pytest.raises(KeyError):
        service.status("g-1")
    assert creative.calls == []


def test_local_goal_refuses_missing_source_and_cross_goal_synthesis():
    service, creative, _, goals, _, results = make_service()
    goals.source_ids = []
    with pytest.raises(GoalVideoContinuationStateError, match="SOURCE_REQUIRED"):
        service.status("g-1")
    goals.source_ids = ["verified-result-1"]
    results.bad_binding = True
    with pytest.raises(GoalVideoContinuationStateError, match="PROVENANCE_INVALID"):
        service.status("g-1")
    assert creative.calls == []


def test_local_source_binding_must_survive_idempotent_read():
    service, creative, _, _, _, _ = make_service()
    creative.source_normalizer.fail = True
    with pytest.raises(GoalVideoContinuationStateError, match="BINDING_MISMATCH"):
        service.status("g-1")


def test_local_goal_will_not_accept_manual_webgpt_return():
    service, _, _, _, _, _ = make_service()
    with pytest.raises(GoalVideoContinuationStateError, match="CANNOT_ADOPT_WEB_RETURN"):
        service.submit("g-1", SimpleNamespace(goal_id="g-1"))


def test_video_goal_source_ids_are_optional_but_bounded_and_nonvideo_forbidden():
    HumanGoalRequest(goal_type=HumanGoalType.VIDEO_CREATIVE,
                     objective="Create a sourced puppy video",
                     source_result_package_ids=["verified-result-1"])
    with pytest.raises(ValueError, match="SOURCE_ONLY_ALLOWED_FOR_VIDEO"):
        # The creation guard rejects using local-video source selections for nonvideo.
        from picotoopet_core.autonomous.goal_service import HumanGoalService
        class Repo:
            def create(self, _):
                raise AssertionError("invalid goal must not be persisted")
        HumanGoalService(Repo()).create(HumanGoalRequest(
            goal_type=HumanGoalType.PRODUCT_RESEARCH, objective="study dogs",
            source_result_package_ids=["verified-result-1"],
        ), idempotency_key="bad-nonvideo")
