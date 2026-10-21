"""Workflow planning and video continuation must agree on a Goal's video mode.

The mode is decided by one predicate, ``constraints["local_video_preferred"] is True``:
ordinary human video Goals opt in; persisted pre-P0 Goals and connected-intake Goals
(``ConnectedIntakeAutopilot``, browser bridge / 4.1 import) carry no flag and keep the manual
Web GPT handoff contract.
"""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from picotoopet_core.autonomous.human_pipeline import HumanGoalWorkflowPlanner
from picotoopet_core.autonomous.models import (
    GoalOrigin,
    GoalRecord,
    GoalStatus,
    PriorityClass,
)
from picotoopet_core.autonomous.video_continuation import (
    GoalVideoContinuationService,
    GoalVideoContinuationStateError,
)

# Exactly the constraints written by intake_autopilot.ConnectedIntakeAutopilot.trigger().
_INTAKE_CONSTRAINTS = {
    "auto_trigger_source": "browser_bridge",
    "connected_product_keys": ["legacy41:p01"],
    "depth": "standard",
    "external_ai_upload_requires_user_action": True,
    "product_visible": True,
    "read_only_research": True,
}


def _goal(constraints: dict) -> GoalRecord:
    now = datetime.now(UTC)
    return GoalRecord(
        goal_id="g-1", workflow_id="workflow-1", origin=GoalOrigin.AUTONOMOUS,
        intent_type="product.research_to_video", priority_class=PriorityClass.P2,
        objective="intake", constraints=constraints, budget_class="local-first",
        pinned=False, status=GoalStatus.READY, idempotency_key="intake-test",
        created_at=now, updated_at=now,
    )


class _Database:
    """A Mac worker already created the Creative job for the Goal; no package yet."""

    def fetchone(self, sql, params):
        if "FROM creative_jobs" in sql:
            return {
                "creative_job_id": "creative-1", "creative_package_id": None,
                "source_set_digest": "d" * 64, "status": "Queued",
            }
        if "FROM creative_goal_source_sets" in sql:
            return {
                "creative_job_id": "creative-1", "goal_id": "g-1",
                "source_set_digest": "d" * 64,
                "discovery_result_hash": "a" * 64, "synthesis_result_hash": "b" * 64,
            }
        raise AssertionError(sql)


def _service(goal: GoalRecord, workflow) -> GoalVideoContinuationService:  # type: ignore[no-untyped-def]
    steps = [
        SimpleNamespace(step_key=step.step_key, task_id=f"task-{step.step_key}")
        for step in workflow.steps
    ]
    records = SimpleNamespace(get_for_task=lambda task_id: SimpleNamespace(
        result_type=("autonomous.discovery.v1" if "research" in task_id
                     else "autonomous.goal_synthesis.v1"),
        object_hash=("a" if "research" in task_id else "b") * 64,
    ))
    return GoalVideoContinuationService(
        database=_Database(), handoffs=SimpleNamespace(),
        creative=SimpleNamespace(
            get_package=lambda job_id: None,
            create_job=lambda **kwargs: pytest.fail("GET must not create a Creative job"),
        ),
        production=SimpleNamespace(),
        goals=SimpleNamespace(get=lambda goal_id: goal),
        workflows=SimpleNamespace(get_workflow=lambda workflow_id: SimpleNamespace(steps=steps)),
        result_records=records, result_store=SimpleNamespace(),
    )


class _LegacyHandoffReached(Exception):
    """Sentinel: the legacy Web GPT path asked for the handoff context."""


def _legacy_probe_service(goal: GoalRecord, workflow) -> GoalVideoContinuationService:  # type: ignore[no-untyped-def]
    service = _service(goal, workflow)

    def context(goal_id: str):  # type: ignore[no-untyped-def]
        raise _LegacyHandoffReached(goal_id)

    service.handoffs = SimpleNamespace(context=context)
    return service


@pytest.mark.parametrize(
    ("label", "flag", "expected_step", "expected_mode"),
    [
        ("human video opt-in", True, "local-creative", "local"),
        ("persisted or connected-intake (no flag)", None, "web-gpt-handoff", "legacy"),
        ("explicit Web GPT opt-out", False, "web-gpt-handoff", "legacy"),
    ],
)
def test_planner_and_continuation_agree_on_video_mode(
    label: str, flag: bool | None, expected_step: str, expected_mode: str
) -> None:
    constraints = dict(_INTAKE_CONSTRAINTS)
    if flag is not None:
        constraints["local_video_preferred"] = flag
    goal = _goal(constraints)
    workflow = HumanGoalWorkflowPlanner().plan(goal)
    assert workflow.steps[-1].step_key == expected_step, label

    if expected_mode == "local":
        record = _service(goal, workflow).status("g-1")
        assert record.continuation_mode == "local", label
        # A local Goal must never adopt a manual Web GPT return.
        with pytest.raises(GoalVideoContinuationStateError, match="CANNOT_ADOPT_WEB_RETURN"):
            _service(goal, workflow).submit("g-1", SimpleNamespace(goal_id="g-1"))
    else:
        # Legacy projection: no local status, and a manual return reaches the handoff context.
        with pytest.raises(KeyError):
            _service(goal, workflow).status("g-1")
        with pytest.raises(_LegacyHandoffReached):
            _legacy_probe_service(goal, workflow).submit("g-1", SimpleNamespace(goal_id="g-1"))
