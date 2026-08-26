from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from picotoopet_core.autonomous.goal_handoff_access import (
    GoalHandoffAccess,
    HandoffAccessError,
)
from picotoopet_core.autonomous.models import (
    GoalOrigin,
    GoalRecord,
    GoalStatus,
    PriorityClass,
)
from picotoopet_core.config.paths import RuntimePaths


def _goal() -> GoalRecord:
    now = datetime(2026, 8, 18, tzinfo=UTC)
    return GoalRecord(
        goal_id="goal-video-1",
        parent_goal_id=None,
        workflow_id="workflow-1",
        origin=GoalOrigin.HUMAN,
        intent_type="product.research_to_video",
        priority_class=PriorityClass.P1,
        objective="研究产品并生成视频方案",
        constraints={"read_only_research": True},
        budget_class="local-first",
        pinned=False,
        score=None,
        status=GoalStatus.COMPLETED,
        idempotency_key="human:test",
        created_at=now,
        updated_at=now,
    )


class FakeGoals:
    def get(self, goal_id: str) -> GoalRecord:
        assert goal_id == "goal-video-1"
        return _goal()


class FakeWorkflows:
    def get_workflow(self, workflow_id: str):  # type: ignore[no-untyped-def]
        assert workflow_id == "workflow-1"
        return SimpleNamespace(
            steps=[SimpleNamespace(step_key="web-gpt-handoff", task_id="task-handoff-1")]
        )


class FakeRecords:
    def get_for_task(self, task_id: str):  # type: ignore[no-untyped-def]
        assert task_id == "task-handoff-1"
        return SimpleNamespace(
            result_type="autonomous.goal_handoff.v1",
            object_hash="a" * 64,
        )


class FakeResultStore:
    def __init__(self, document: dict[str, object]) -> None:
        self.document = document

    def read_json(self, object_hash: str, *, max_bytes: int) -> dict[str, object]:
        assert object_hash == "a" * 64
        assert max_bytes <= 128 * 1024
        return dict(self.document)


def _access(tmp_path: Path, document: dict[str, object]) -> GoalHandoffAccess:
    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.ensure()
    return GoalHandoffAccess(
        paths=paths,
        goals=FakeGoals(),
        workflows=FakeWorkflows(),
        result_records=FakeRecords(),
        result_store=FakeResultStore(document),
    )


def test_handoff_access_returns_verified_metadata_and_managed_file(tmp_path: Path) -> None:
    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.ensure()
    payload = b"verified-handoff-zip"
    package = paths.autonomous_handoffs_dir / "goal-video-1-1234.zip"
    package.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    access = _access(
        tmp_path,
        {
            "schema_version": "1.0",
            "goal_id": "goal-video-1",
            "handoff_ready": True,
            "package_name": package.name,
            "package_sha256": digest,
            "package_size_bytes": len(payload),
            "prompt_version": "web-gpt-master-v1.0",
            "manual_web_gpt_upload_required": True,
        },
    )

    metadata = access.metadata("goal-video-1")
    resolved = access.verified_package("goal-video-1")

    assert metadata.handoff_ready is True
    assert metadata.package_name == package.name
    assert metadata.package_sha256 == digest
    assert metadata.manual_web_gpt_upload_required is True
    assert resolved == package.resolve()
    assert "runtime" not in metadata.model_dump_json()
    assert "Prompt-Version: web-gpt-master-v1.0" in access.fixed_prompt("goal-video-1")


def test_handoff_access_rejects_tampering_and_path_escape(tmp_path: Path) -> None:
    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.ensure()
    package = paths.autonomous_handoffs_dir / "safe.zip"
    package.write_bytes(b"tampered")

    bad_hash = _access(
        tmp_path,
        {
            "schema_version": "1.0",
            "goal_id": "goal-video-1",
            "handoff_ready": True,
            "package_name": "safe.zip",
            "package_sha256": "0" * 64,
            "package_size_bytes": len(b"tampered"),
            "prompt_version": "web-gpt-master-v1.0",
            "manual_web_gpt_upload_required": True,
        },
    )
    with pytest.raises(HandoffAccessError, match="integrity"):
        bad_hash.verified_package("goal-video-1")

    escaped = _access(
        tmp_path,
        {
            "schema_version": "1.0",
            "goal_id": "goal-video-1",
            "handoff_ready": True,
            "package_name": "../outside.zip",
            "package_sha256": "0" * 64,
            "package_size_bytes": 1,
            "prompt_version": "web-gpt-master-v1.0",
            "manual_web_gpt_upload_required": True,
        },
    )
    with pytest.raises(HandoffAccessError, match="package name"):
        escaped.metadata("goal-video-1")
