"""Workflow planning and video continuation must agree on a Goal's video mode.

Connected-intake Goals (browser bridge / 4.1 import) are ``product.research_to_video`` Goals
created by ``ConnectedIntakeAutopilot``; they carry no ``local_video_preferred`` constraint.
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
from picotoopet_core.autonomous.video_continuation import GoalVideoContinuationService

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


def test_human_video_goal_plan_and_continuation_agree_on_local_mode() -> None:
    # Control: the human-created shape (flag present) is consistent, so this guards the fixture.
    goal = _goal({**_INTAKE_CONSTRAINTS, "local_video_preferred": True})
    workflow = HumanGoalWorkflowPlanner().plan(goal)
    assert workflow.steps[-1].step_key == "local-creative"
    assert _service(goal, workflow).status("g-1").continuation_mode == "local"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "BLOCKED: production owner G006 (#91). HumanGoalWorkflowPlanner.plan() plans the native "
        "local-creative stage for every video Goal, but GoalVideoContinuationService._local_goal() "
        "(autonomous/video_continuation.py) only recognises Goals with constraint "
        "local_video_preferred=True. Connected-intake Goals "
        "(autonomous/intake_autopilot.py::trigger) never set it, so they are planned local yet "
        "projected through the legacy Web GPT path (status() -> KeyError/provenance 409; "
        "submit() -> missing web-gpt-handoff step). "
        "Make planner and continuation use one predicate."
    ),
)
def test_connected_intake_goal_plan_and_continuation_agree_on_mode() -> None:
    goal = _goal(dict(_INTAKE_CONSTRAINTS))
    workflow = HumanGoalWorkflowPlanner().plan(goal)
    planned_local = workflow.steps[-1].step_key == "local-creative"

    record = _service(goal, workflow).status("g-1")  # raises today: projected as legacy

    assert (record.continuation_mode == "local") is planned_local
