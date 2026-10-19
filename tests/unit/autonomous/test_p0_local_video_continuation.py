"""P0: canonical local Goal workflow projection, no GET-side creative job duplication."""

from types import SimpleNamespace

import pytest

from picotoopet_core.autonomous.video_continuation import (
    GoalVideoContinuationService,
    GoalVideoContinuationStateError,
)
from picotoopet_core.creative.models import CreativeQualityOutcome


class Database:
    def __init__(self):
        self.created_by_worker = False
        self.package_ready = False
        self.production_created_by_worker = False
        self.invalid_provenance = False

    def fetchone(self, sql, params):
        if "FROM creative_jobs" in sql:
            if not self.created_by_worker:
                return None
            return {
                "creative_job_id": "creative-persisted",
                "creative_package_id": "creative-package" if self.package_ready else None,
                "source_set_digest": "d" * 64,
                "status": "CreativeReady" if self.package_ready else "Queued",
            }
        if "FROM creative_goal_source_sets" in sql:
            assert params == ("creative-persisted", "g-1")
            return {
                "creative_job_id": "creative-persisted",
                "goal_id": "g-1",
                "source_set_digest": "d" * 64,
                "discovery_result_hash": "a" * 64,
                "synthesis_result_hash": ("f" if self.invalid_provenance else "b") * 64,
            }
        if "FROM production_jobs" in sql:
            assert params == ("creative-package",)
            return ({"production_job_id": "production-persisted", "status": "Ready"}
                    if self.production_created_by_worker else None)
        raise AssertionError(sql)


class Creative:
    def __init__(self, db):
        self.db = db
        self.calls = []

    def create_job(self, **kwargs):
        self.calls.append(kwargs)
        raise AssertionError("GET must not create duplicate Creative jobs")

    def get_package(self, creative_job_id):
        assert creative_job_id == "creative-persisted"
        if not self.db.package_ready:
            return None
        return SimpleNamespace(
            creative_package_id="creative-package",
            package_digest="c" * 64,
            quality_outcome=CreativeQualityOutcome.PASS,
            manifest={"project_key": "goal-g-1", "source_set_digest": "d" * 64},
        )


class Production:
    def __init__(self):
        self.keys = []

    def create_job(self, request):
        assert request.creative_package_id == "creative-package"
        self.keys.append(request.idempotency_key)
        return SimpleNamespace(
            production_job_id="production-persisted",
            status=SimpleNamespace(value="Ready"),
        )


class Goals:
    def get(self, goal_id):
        assert goal_id == "g-1"
        return SimpleNamespace(
            goal_id="g-1", workflow_id="workflow-1",
            intent_type="video.creative",
            objective="Generate a real evidence-backed pet video",
            constraints={"local_video_preferred": True},
        )


class Workflows:
    def get_workflow(self, workflow_id):
        assert workflow_id == "workflow-1"
        return SimpleNamespace(steps=[
            SimpleNamespace(step_key="research-evidence", task_id="discovery-task"),
            SimpleNamespace(step_key="evidence-synthesis", task_id="synthesis-task"),
            SimpleNamespace(step_key="local-creative", task_id="creative-task"),
        ])


class Records:
    def get_for_task(self, task_id):
        return SimpleNamespace(
            result_type=("autonomous.discovery.v1" if task_id == "discovery-task"
                         else "autonomous.goal_synthesis.v1"),
            object_hash=("a" if task_id == "discovery-task" else "b") * 64,
        )


class Results:
    def read_json(self, object_hash, *, max_bytes):
        assert max_bytes <= 256 * 1024
        return {"schema_version": "1.0", "goal_id": "g-1", "evidence_ids": ["ev-1"]}


def make_service():
    db = Database()
    creative = Creative(db)
    production = Production()
    return (GoalVideoContinuationService(
        database=db, handoffs=SimpleNamespace(),
        creative=creative, production=production,
        goals=Goals(), workflows=Workflows(),
        result_records=Records(), result_store=Results(),
    ), db, creative, production)


def test_get_before_mac_worker_creates_job_is_pending_not_synthetic():
    service, db, creative, production = make_service()
    with pytest.raises(KeyError):
        service.status("g-1")
    assert creative.calls == []
    assert production.keys == []


def test_native_mac_worker_job_reuses_exact_local_core_identity_for_production():
    service, db, creative, production = make_service()
    db.created_by_worker = True
    waiting = service.status("g-1")
    assert waiting.continuation_mode == "local"
    assert waiting.handoff_sha256 == "a" * 64
    assert waiting.return_sha256 == "b" * 64
    assert waiting.creative_package_id is None
    assert waiting.production_job_id is None
    assert waiting.creative_job_id == "creative-persisted"
    db.package_ready = True
    before_production = service.status("g-1")
    assert before_production.production_job_id is None
    # Actual Mac Worker wraps the four-stage Creative handler and durably
    # creates canonical Production after a PASS package; GET never enqueues.
    db.production_created_by_worker = True
    ready = service.status("g-1")
    assert ready.creative_package_id == "creative-package"
    assert ready.creative_package_digest == "c" * 64
    assert ready.production_job_id == "production-persisted"
    assert ready.production_status == "Ready"
    assert service.status("g-1").production_job_id == ready.production_job_id
    assert creative.calls == []
    assert production.keys == []


def test_mutated_synthesis_hash_closes_gate_without_creating_production():
    service, db, _, production = make_service()
    db.created_by_worker = True
    db.package_ready = True
    db.invalid_provenance = True
    with pytest.raises(GoalVideoContinuationStateError, match="SOURCE_PROVENANCE_INVALID"):
        service.status("g-1")
    assert production.keys == []


def test_local_goal_rejects_manual_webgpt_return():
    service, _, creative, _ = make_service()
    with pytest.raises(GoalVideoContinuationStateError, match="CANNOT_ADOPT_WEB_RETURN"):
        service.submit("g-1", SimpleNamespace(goal_id="g-1"))
    assert creative.calls == []
