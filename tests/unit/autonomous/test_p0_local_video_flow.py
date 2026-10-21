"""P0 #91: real Goal-to-local-Creative routing and durable schema contracts."""

from datetime import UTC, datetime

from picotoopet_core.autonomous.human_pipeline import HumanGoalWorkflowPlanner
from picotoopet_core.autonomous.models import GoalOrigin, GoalRecord, GoalStatus, PriorityClass
from picotoopet_core.db.database import Database


def _goal(intent_type: str) -> GoalRecord:
    # ── Only fixed Goal intent and Core-owned workflow configuration are supplied. ──
    now = datetime.now(UTC)
    return GoalRecord(
        goal_id="p0-goal", workflow_id="p0-workflow", origin=GoalOrigin.HUMAN,
        intent_type=intent_type, priority_class=PriorityClass.P1,
        objective="Generate a factual pet video", constraints={
            "read_only_research": True, "depth": "quick",
            "local_video_preferred": intent_type in {"video.creative", "product.research_to_video"},
        },
        budget_class="local-first", pinned=False, status=GoalStatus.READY,
        idempotency_key="p0-test", created_at=now, updated_at=now,
    )


def test_ordinary_video_uses_native_local_creative_not_web_gpt() -> None:
    # ── Ordinary video goes to canonical Creative without a mandatory manual upload. ──
    workflow = HumanGoalWorkflowPlanner().plan(_goal("video.creative"))
    steps = list(workflow.steps)
    assert [s.step_key for s in steps] == [
        "research-evidence", "evidence-synthesis", "local-creative",
    ]
    assert steps[-1].task_type == "autonomous.goal_creative.v1"
    assert steps[-1].required_capability == "local.goal.creative"
    assert steps[-1].depends_on == ["evidence-synthesis"]
    assert all(step.task_type != "autonomous.goal_handoff.v1" for step in steps)


def test_product_research_to_video_uses_same_local_pipeline() -> None:
    # ── Product-to-video uses identical scheduling with different Goal identity. ──
    workflow = HumanGoalWorkflowPlanner().plan(_goal("product.research_to_video"))
    assert workflow.steps[-1].task_type == "autonomous.goal_creative.v1"


def test_pure_research_never_creates_video_tasks() -> None:
    # ── Non-video work stays on the original two-stage read-only workflow. ──
    workflow = HumanGoalWorkflowPlanner().plan(_goal("product.research"))
    assert len(workflow.steps) == 2
    assert all("creative" not in step.step_key for step in workflow.steps)


def test_goal_source_migration_is_idempotent(tmp_path) -> None:
    # ── Schema 24 is the only Goal linkage; business result FKs remain unchanged. ──
    database = Database(tmp_path / "core.db")
    database.open()
    try:
        database.apply_migrations()
        database.apply_migrations()
        assert database.scalar(
            "SELECT COUNT(*) FROM schema_migrations WHERE version=24"
        ) == 1
        columns = {
            row["name"] for row in database.fetchall(
                "PRAGMA table_info(creative_goal_source_sets)"
            )
        }
        assert {
            "creative_job_id", "goal_id", "source_set_digest",
            "source_set_json", "discovery_result_hash", "synthesis_result_hash",
        } <= columns
    finally:
        database.close()


def test_persisted_legacy_and_auto_video_goals_keep_handoff_contract() -> None:
    # ── Missing opt-in must not reinterpret already-persisted workflow intent. ─
    from picotoopet_core.autonomous.models import GoalOrigin

    legacy = _goal("product.research_to_video")
    legacy.constraints.pop("local_video_preferred")
    steps = HumanGoalWorkflowPlanner().plan(legacy).steps
    assert steps[-1].step_key == "web-gpt-handoff"
    assert steps[-1].task_type == "autonomous.goal_handoff.v1"
    autonomous = legacy.model_copy(update={"origin": GoalOrigin.AUTONOMOUS})
    assert HumanGoalWorkflowPlanner().plan(autonomous).steps[-1].task_type == (
        "autonomous.goal_handoff.v1"
    )
