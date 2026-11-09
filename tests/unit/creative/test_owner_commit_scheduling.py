from __future__ import annotations

import pytest

from picotoopet_core.autonomous.owner_structured_review import (
    OwnerStructuredReviewCommitRequest,
    OwnerStructuredReviewService,
)
from picotoopet_core.creative.repository import CreativeRepository
from picotoopet_core.creative.service import (
    CREATIVE_TASK_TYPE,
    awaits_owner_commit,
    schedule_after_owner_commit,
)
from picotoopet_core.creative.state_spine import STATIC_PET_STORY_POLICY
from picotoopet_core.db.database import Database
from tests.unit.autonomous.test_owner_structured_review import (
    JOB_ID,
    OBJECTIVE,
    _preview_request,
    _principal,
)

pytest_plugins = ("tests.unit.autonomous.test_owner_structured_review",)


@pytest.fixture(autouse=True)
def _ready_job(review_database: Database) -> None:
    review_database.execute(
        "UPDATE creative_jobs SET status='Ready' WHERE creative_job_id=?", (JOB_ID,)
    )


def _tasks(database: Database) -> int:
    return database.scalar(
        "SELECT COUNT(*) FROM tasks WHERE task_type=?", (CREATIVE_TASK_TYPE,)
    )


_LAST: dict[str, tuple] = {}


def _commit(database: Database, policy: str | None, key: str):
    service = OwnerStructuredReviewService(database)
    principal = _principal()
    request, _ = _preview_request(service, principal)
    request = request.model_copy(update={"story_policy_opt_in": policy})
    preview = service.preview(request, principal)
    commit_request = OwnerStructuredReviewCommitRequest(
        preview_request=request,
        source_revision_digest=preview.source_revision_digest,
        review_digest=preview.review_digest,
        preview_digest=preview.preview_digest,
    )
    _LAST[key] = (service, commit_request, principal)
    return service.commit(commit_request, principal, idempotency_key=key)


def _replay(key: str):
    service, commit_request, principal = _LAST[key]
    return service.commit(commit_request, principal, idempotency_key=key)


def test_only_new_goal_pet_only_v2_waits_for_owner_commit() -> None:
    assert awaits_owner_commit("creative.content_plan.v2", OBJECTIVE) is True
    assert awaits_owner_commit("creative.content_plan.v1", OBJECTIVE) is False
    assert awaits_owner_commit("creative.content_plan.v2", "make a product ad") is False
    assert awaits_owner_commit("creative.content_plan.v2", None) is False


def test_nothing_is_scheduled_before_any_owner_commit(review_database: Database) -> None:
    assert schedule_after_owner_commit(review_database, JOB_ID) is False
    assert schedule_after_owner_commit(review_database, "unknown-job") is False
    assert _tasks(review_database) == 0


def test_valid_commit_schedules_exactly_one_task_and_replay_is_idempotent(
    review_database: Database,
) -> None:
    _commit(review_database, STATIC_PET_STORY_POLICY, "sched-1")
    assert _tasks(review_database) == 1
    payload_job = review_database.scalar(
        "SELECT payload_json FROM tasks WHERE task_type=?", (CREATIVE_TASK_TYPE,)
    )
    assert JOB_ID in payload_job

    _replay("sched-1")  # exact replay
    assert schedule_after_owner_commit(review_database, JOB_ID) is True  # direct re-call
    assert _tasks(review_database) == 1


def test_commit_without_static_policy_schedules_nothing(review_database: Database) -> None:
    _commit(review_database, None, "sched-no-policy")
    assert _tasks(review_database) == 0


@pytest.mark.parametrize("column", ["objective_digest", "source_set_digest"])
def test_stale_commit_schedules_nothing(review_database: Database, column: str) -> None:
    review_database.execute(
        f"UPDATE creative_jobs SET {column}=? WHERE creative_job_id=?", ("a" * 64, JOB_ID)
    )
    assert schedule_after_owner_commit(review_database, JOB_ID) is False
    assert _tasks(review_database) == 0


def test_withdrawn_policy_blocks_later_scheduling(review_database: Database) -> None:
    first = _commit(review_database, STATIC_PET_STORY_POLICY, "sched-a")
    review_database.execute("DELETE FROM tasks")  # isolate the second decision
    review_database.execute(
        "UPDATE canonical_evidence SET captured_at='2000-01-01T00:00:00+00:00' "
        "WHERE evidence_id=?",
        (first.commitment_id,),
    )
    _commit(review_database, None, "sched-withdraw")
    assert schedule_after_owner_commit(review_database, JOB_ID) is False
    assert _tasks(review_database) == 0


def test_non_ready_job_is_never_scheduled(review_database: Database) -> None:
    _commit(review_database, STATIC_PET_STORY_POLICY, "sched-b")
    review_database.execute("DELETE FROM tasks")
    review_database.execute(
        "UPDATE creative_jobs SET status='NeedsHuman' WHERE creative_job_id=?", (JOB_ID,)
    )
    assert schedule_after_owner_commit(review_database, JOB_ID) is False
    assert CreativeRepository(review_database).get_job(JOB_ID).status.value == "NeedsHuman"
    assert _tasks(review_database) == 0


def _service(database: Database, tmp_path):
    from picotoopet_core.config.paths import RuntimePaths
    from picotoopet_core.creative.service import CreativeIntelligenceService
    from picotoopet_core.creative.source import CreativeSourceNormalizer
    from picotoopet_core.creative.store import CreativeArtifactStore
    from picotoopet_core.queue.repository import QueueRepository

    return CreativeIntelligenceService(
        repository=CreativeRepository(database),
        source_normalizer=CreativeSourceNormalizer(database),
        store=CreativeArtifactStore(RuntimePaths.from_root(tmp_path / "runtime")),
        queue=QueueRepository(database),
    )


def _second_goal(database: Database, goal_id: str) -> None:
    row = dict(database.fetchone("SELECT * FROM autonomous_goals"))
    row["goal_id"] = goal_id
    row["idempotency_key"] = f"idem-{goal_id}"
    columns = ",".join(row)
    database.execute(
        f"INSERT INTO autonomous_goals({columns}) VALUES ({','.join('?' for _ in row)})",
        tuple(row.values()),
    )


def test_create_goal_job_holds_new_pet_v2_but_not_v1_or_non_pet_v2(
    review_database: Database, tmp_path
) -> None:
    from picotoopet_core.creative.source import CreativeSourceNormalizer

    service = _service(review_database, tmp_path)
    source = CreativeSourceNormalizer(review_database).load_persisted_source_set(JOB_ID)
    cases = [
        ("goal-pet-v2", "creative.content_plan.v2", OBJECTIVE, 0),
        ("goal-pet-v1", "creative.content_plan.v1", OBJECTIVE, 1),
        ("goal-plain-v2", "creative.content_plan.v2", "Make a product promotion video", 1),
    ]
    for goal_id, profile, objective, expected_new_tasks in cases:
        _second_goal(review_database, goal_id)
        before = _tasks(review_database)
        job = service.create_goal_job(
            goal_id=goal_id,
            source_set=source.model_copy(update={"project_key": f"goal-{goal_id}"}),
            discovery_result_hash="d" * 64,
            synthesis_result_hash="e" * 64,
            creative_objective=objective,
            creative_profile=profile,
        )
        assert _tasks(review_database) - before == expected_new_tasks, goal_id
        assert job.status.value == "Ready"
