"""P0: fresh local three-shot Goal uses real Creative v2; persisted jobs never re-profile."""

from types import SimpleNamespace

import pytest

from picotoopet_core.autonomous.local_creative import GoalLocalCreativeCoordinator
from picotoopet_core.creative.models import CreativeProfile


class _ProfileDatabase:
    def __init__(self, existing: str | None = None) -> None:
        self.existing = existing
        self.calls = 0

    def fetchone(self, query: str, args: tuple[str]) -> dict[str, str] | None:
        # Source identity   : lookup is keyed to the same immutable goal-video idempotency key.
        assert "FROM creative_jobs WHERE idempotency_key=?" in query
        assert args == ("goal-video:test-goal",)
        self.calls += 1
        return {"creative_profile": self.existing} if self.existing is not None else None


def _coordinator(existing: str | None = None) -> tuple[GoalLocalCreativeCoordinator, _ProfileDatabase]:
    database = _ProfileDatabase(existing)
    creative = SimpleNamespace(repository=SimpleNamespace(database=database))
    coordinator = GoalLocalCreativeCoordinator(
        goals=None,
        workflows=None,
        result_records=None,
        result_store=None,
        creative=creative,
    )
    return coordinator, database


@pytest.mark.parametrize(
    "objective",
    [
        "Exactly 3 shots, text-to-video only; each shot 4 seconds.",
        "请生成3个镜头，每个4秒，质量优先故事。",
        "Use the quality-first story gate for this pet video.",
    ],
)
def test_new_explicit_three_shot_or_story_goal_selects_actual_v2(objective: str) -> None:
    # Actual activation : v1 has no Video Bible stage, so only v2 runs the existing story gate.
    coordinator, db = _coordinator()
    goal = SimpleNamespace(goal_id="test-goal", objective=objective)
    assert coordinator._profile_for_goal(goal) == CreativeProfile.CONTENT_PLAN_V2.value
    assert db.calls == 1


@pytest.mark.parametrize(
    "objective",
    [
        "Generate a factual pet video.",
        "Exactly 4 shots, 5 seconds each, and no Story Gate.",
        "Create a two-shot product montage.",
    ],
)
def test_unspecified_or_other_count_keeps_legacy_v1(objective: str) -> None:
    # Fresh defaults    : ordinary and non-three-shot Goals continue to choose v1.
    # Durable lookup    : first check for a stored profile even when the Goal is ordinary.
    coordinator, db = _coordinator()
    goal = SimpleNamespace(goal_id="test-goal", objective=objective)
    assert coordinator._profile_for_goal(goal) == CreativeProfile.CONTENT_PLAN_V1.value
    assert db.calls == 1


@pytest.mark.parametrize(
    "existing",
    [CreativeProfile.CONTENT_PLAN_V1.value, CreativeProfile.CONTENT_PLAN_V2.value],
)
def test_existing_three_shot_idempotent_job_keeps_its_original_profile(existing: str) -> None:
    # Recovery contract : after restart, a previously persisted v1 or v2 job is never migrated.
    coordinator, db = _coordinator(existing)
    goal = SimpleNamespace(goal_id="test-goal", objective="Exactly 3 shots, 4 seconds per shot")
    assert coordinator._profile_for_goal(goal) == existing
    assert db.calls == 1


@pytest.mark.parametrize(
    "objective",
    [
        "Generate a factual pet video.",
        "Exactly 2 shots, 4 seconds each.",
        "Exactly 4 shots, no Story Gate.",
    ],
)
@pytest.mark.parametrize(
    "existing",
    [CreativeProfile.CONTENT_PLAN_V1.value, CreativeProfile.CONTENT_PLAN_V2.value],
)
def test_existing_non_three_shot_goal_preserves_immutable_profile(
    objective: str, existing: str
) -> None:
    # Replay priority   : stored v1/v2 outranks fresh directive selection for every Goal.
    # Old behavior      : a stored v2 for an ordinary Goal was mis-selected as v1.
    coordinator, db = _coordinator(existing)
    goal = SimpleNamespace(goal_id="test-goal", objective=objective)
    assert coordinator._profile_for_goal(goal) == existing
    assert db.calls == 1
