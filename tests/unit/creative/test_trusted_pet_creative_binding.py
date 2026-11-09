from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from picotoopet_core.autonomous.owner_structured_review import (
    OwnerStructuredReviewCommitRequest,
    OwnerStructuredReviewService,
)
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.creative import execution as execution_module
from picotoopet_core.creative.execution import (
    CreativeIntelligenceCoordinator,
    CreativeTaskPayload,
    TrustedPetCreativeBindingError,
    load_trusted_pet_creative_binding,
    verify_owner_commitment_in_ledger,
)
from picotoopet_core.creative.repository import CreativeRepository
from picotoopet_core.creative.source import CreativeSourceNormalizer
from picotoopet_core.creative.state_spine import STATIC_PET_STORY_POLICY
from picotoopet_core.creative.store import CreativeArtifactStore
from picotoopet_core.db.database import Database
from picotoopet_core.domain.enums import TaskStatus
from picotoopet_core.domain.models import TaskRecord
from picotoopet_core.production.compiler import compile_production_plan
from picotoopet_core.queue.diagnostic_repository import DiagnosticQueueRepository
from tests.unit.autonomous.test_owner_structured_review import (
    JOB_ID,
    _preview_request,
    _principal,
)

pytest_plugins = ("tests.unit.autonomous.test_owner_structured_review",)


def _commit_with_policy(
    database: Database,
    policy: str | None = STATIC_PET_STORY_POLICY,
    *,
    key: str = "trusted-pet-creative-binding",
) -> str:
    """Commit through the REAL owner-review service; the policy is the owner's typed choice."""

    database.execute(
        "UPDATE creative_jobs SET status='Ready' WHERE creative_job_id=?",
        (JOB_ID,),
    )
    service = OwnerStructuredReviewService(database)
    principal = _principal()
    preview_request, _ = _preview_request(service, principal)
    preview_request = preview_request.model_copy(update={"story_policy_opt_in": policy})
    preview = service.preview(preview_request, principal)
    assert preview.outcome == "READY"
    commit = service.commit(
        OwnerStructuredReviewCommitRequest(
            preview_request=preview_request,
            source_revision_digest=preview.source_revision_digest,
            review_digest=preview.review_digest,
            preview_digest=preview.preview_digest,
        ),
        principal,
        idempotency_key=key,
    )
    return commit.commitment_id


def test_loads_only_canonical_owner_commit_with_exact_policy(
    review_database: Database,
) -> None:
    commitment_id = _commit_with_policy(review_database)
    job = CreativeRepository(review_database).get_job(JOB_ID)

    binding = load_trusted_pet_creative_binding(review_database, job)

    assert binding.commitment_id == commitment_id
    assert binding.story_policy_opt_in == STATIC_PET_STORY_POLICY
    assert binding.facts.source_set_digest == job.source_set_digest
    assert binding.facts.objective_digest == job.objective_digest


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("wrong-policy", "TRUSTED_STORY_POLICY_NOT_SELECTED"),
        ("wrong-subject", "TRUSTED_STATE_FACTS_COMMITMENT_MISSING"),
        ("stale-objective", "TRUSTED_STATE_FACTS_OBJECTIVE_MISMATCH"),
        ("stale-source", "TRUSTED_STATE_FACTS_SOURCE_MISMATCH"),
    ],
)
def test_binding_fails_closed_for_policy_identity_and_staleness(
    review_database: Database,
    mutation: str,
    reason: str,
) -> None:
    commitment_id = _commit_with_policy(
        review_database,
        None if mutation == "wrong-policy" else STATIC_PET_STORY_POLICY,
    )
    if mutation == "wrong-subject":
        review_database.execute(
            "UPDATE canonical_evidence SET subject_key=? WHERE evidence_id=?",
            ("pet:other-subject", commitment_id),
        )
    elif mutation == "stale-objective":
        review_database.execute(
            "UPDATE creative_jobs SET objective_digest=? WHERE creative_job_id=?",
            ("a" * 64, JOB_ID),
        )
    elif mutation == "stale-source":
        review_database.execute(
            "UPDATE creative_jobs SET source_set_digest=? WHERE creative_job_id=?",
            ("b" * 64, JOB_ID),
        )
    job = CreativeRepository(review_database).get_job(JOB_ID)

    with pytest.raises(TrustedPetCreativeBindingError, match=reason):
        load_trusted_pet_creative_binding(review_database, job)


def test_missing_commitment_needs_human_before_any_model_call(
    review_database: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review_database.execute(
        "UPDATE creative_jobs SET status='Ready' WHERE creative_job_id=?",
        (JOB_ID,),
    )
    job = CreativeRepository(review_database).get_job(JOB_ID)
    payload = SimpleNamespace(
        creative_job_id=JOB_ID,
        source_set_digest=job.source_set_digest,
        creative_profile=job.creative_profile,
    )
    monkeypatch.setattr(
        CreativeTaskPayload,
        "from_task",
        classmethod(lambda cls, task: payload),
    )

    class NoCallAdapter:
        calls = 0

        def run(self, profile, context, *, correction=None):  # type: ignore[no-untyped-def]
            self.calls += 1
            raise AssertionError("trusted preflight must stop before the model")

    adapter = NoCallAdapter()
    paths = RuntimePaths.from_root(tmp_path / "runtime")
    coordinator = CreativeIntelligenceCoordinator(
        database=review_database,
        queue=DiagnosticQueueRepository(review_database),
        repository=CreativeRepository(review_database),
        source_normalizer=CreativeSourceNormalizer(review_database),
        store=CreativeArtifactStore(paths),
        adapter=adapter,
        configured_model_id="synthetic:no-call",
    )
    now = datetime.now(UTC)
    task = TaskRecord(
        task_id="synthetic-task",
        task_type=CreativeIntelligenceCoordinator.TASK_TYPE,
        status=TaskStatus.RUNNING,
        priority=0,
        payload={},
        attempt_count=1,
        max_attempts=1,
        timeout_seconds=60,
        created_at=now,
        updated_at=now,
    )

    result = coordinator.handler(task)

    assert result.summary["status"] == "NeedsHuman"
    assert adapter.calls == 0
    final = CreativeRepository(review_database).get_job(JOB_ID)
    assert final.failure_code == "TRUSTED_STATE_FACTS_COMMITMENT_MISSING"
    assert review_database.scalar(
        "SELECT COUNT(*) FROM creative_stage_runs WHERE creative_job_id=?", (JOB_ID,)
    ) == 0


def _run_full(
    review_database: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _commit_with_policy(review_database)
    repository = CreativeRepository(review_database)
    job = repository.get_job(JOB_ID)
    source = CreativeSourceNormalizer(review_database)
    source_set = source.load_persisted_source_set(JOB_ID)
    finding_ref = source_set.findings[0].source_finding_ref
    evidence_id = source_set.evidence_ids[0]
    ideas = {
        "schema_version": "1.0",
        "creative_profile": "creative.content_plan.v1",
        "ideas": [
            {
                "idea_id": f"idea-{rank:03d}",
                "rank": rank,
                "title": f"Synthetic calm pet idea {rank}",
                "audience_problem": "show a trustworthy calm pet moment",
                "hook": "one brief blink",
                "angle": "quiet observation",
                "value_proposition": "recognizable continuity",
                "format_hint": "three-shot short video",
                "confidence": 0.9,
                "source_finding_refs": [finding_ref],
                "source_evidence_ids": [evidence_id],
                "claim_risk": "LOW",
                "warnings": [],
            }
            for rank in range(1, 4)
        ],
        "needs_deep_ai": False,
        "needs_human": False,
    }
    brief = {
        "schema_version": "1.0",
        "creative_profile": "creative.content_plan.v1",
        "selected_idea_id": "idea-001",
        "target_audience": "pet owners",
        "customer_problem": "identity drift across generated shots",
        "value_proposition": "a calm recognizable moment",
        "primary_hook": "one brief blink",
        "emotional_tone": "calm",
        "content_format": "three-shot short video",
        "output_profile_id": "video.landscape.v1",
        "duration_min_seconds": 12,
        "duration_max_seconds": 12,
        "message_hierarchy": ["blink", "breathing", "closer observation"],
        "required_source_finding_refs": [finding_ref],
        "required_source_evidence_ids": [evidence_id],
        "prohibited_claims": [],
        "cta_intent": "end on a closer calm view",
        "continuity_notes": [],
        "needs_deep_ai": False,
        "needs_human": False,
    }
    script = {
        "schema_version": "1.0",
        "creative_profile": "creative.content_plan.v1",
        "script_id": "script-static-pet",
        "title": "Blink, breathe, stay",
        "target_duration_seconds": 12,
        "beats": [
            {
                "beat_id": f"beat-{order:03d}",
                "order": order,
                "duration_seconds": 4,
                "voiceover": None,
                "on_screen_text": None,
                "visual_intent": intent,
                "claim_source_evidence_ids": [],
                "unsupported_claim": False,
            }
            for order, intent in enumerate(
                ("brief blink and reopen", "subtle breathing detail", "calm framing payoff"),
                start=1,
            )
        ],
        "cta_beat_id": "beat-003",
        "warnings": [],
        "needs_deep_ai": False,
        "needs_human": False,
    }
    proposal = {
        "schema_version": "state_spine_proposal.v1",
        "shots": [
            {
                "shot_id": "shot-001",
                "beat_id": "beat-001",
                "event": "BLINK_AND_REOPEN",
                "creative_emphasis": "CALM_OBSERVATIONAL",
                "camera_framing": "locked medium shot",
            },
            {
                "shot_id": "shot-002",
                "beat_id": "beat-002",
                "event": "SUBTLE_BREATHING",
                "creative_emphasis": "DETAIL",
                "camera_framing": "locked close-up",
            },
            {
                "shot_id": "shot-003",
                "beat_id": "beat-003",
                "event": "SUBTLE_BREATHING",
                "creative_emphasis": "CALM_OBSERVATIONAL",
                "camera_framing": "locked medium shot",
            },
        ],
        "needs_deep_ai": False,
        "needs_human": False,
    }

    class SyntheticAdapter:
        def __init__(self) -> None:
            self.responses = [ideas, brief, script, proposal]
            self.calls = 0
            self.profiles = []

        def run(self, profile, context, *, correction=None):  # type: ignore[no-untyped-def]
            self.calls += 1
            self.profiles.append(profile)
            return self.responses.pop(0)

    adapter = SyntheticAdapter()
    payload = SimpleNamespace(
        creative_job_id=JOB_ID,
        source_set_digest=job.source_set_digest,
        creative_profile=job.creative_profile,
    )
    monkeypatch.setattr(
        CreativeTaskPayload,
        "from_task",
        classmethod(lambda cls, task: payload),
    )
    paths = RuntimePaths.from_root(tmp_path / "runtime")
    coordinator = CreativeIntelligenceCoordinator(
        database=review_database,
        queue=DiagnosticQueueRepository(review_database),
        repository=repository,
        source_normalizer=source,
        store=CreativeArtifactStore(paths),
        adapter=adapter,
        configured_model_id="synthetic:locked",
    )
    now = datetime.now(UTC)
    result = coordinator.handler(
        TaskRecord(
            task_id="synthetic-trusted-task",
            task_type=coordinator.TASK_TYPE,
            status=TaskStatus.RUNNING,
            priority=0,
            payload={},
            attempt_count=1,
            max_attempts=1,
            timeout_seconds=60,
            created_at=now,
            updated_at=now,
        )
    )

    return adapter, result, repository


def test_trusted_path_binds_unlocked_bible_and_compiles_three_locked_prompts(
    review_database: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, result, repository = _run_full(review_database, tmp_path, monkeypatch)
    assert result.summary["status"] == "creative_ready"
    assert adapter.calls == 4
    assert adapter.profiles[-1].result_model is not adapter.profiles[0].result_model
    package = repository.package_for(JOB_ID)
    assert package is not None
    plan = compile_production_plan(str(uuid4()), package.manifest, package.package_digest)
    assert [task.frame_count for task in plan.tasks] == [97, 97, 97]
    assert [task.fps for task in plan.tasks] == [24, 24, 24]
    facts = load_trusted_pet_creative_binding(review_database, repository.get_job(JOB_ID)).facts
    required = [
        facts.subject_lock.subject_id,
        facts.subject_lock.species,
        facts.subject_lock.breed_or_type,
        facts.subject_lock.coat_or_appearance,
        *facts.subject_lock.distinguishing_marks,
        facts.pose_lock.body_pose,
        facts.pose_lock.head_direction,
        facts.pose_lock.support_surface,
        facts.scene_lock.environment,
        facts.scene_lock.lighting,
        *facts.scene_lock.temporary_accessories,
        "locked-off tripod camera, no camera movement",
        ", ".join(facts.camera_lock.allowed_framings),
    ]
    for task in plan.tasks:
        assert all(value in task.positive_prompt for value in required)


def test_prompt_lock_loss_fails_closed_without_package_handoff_or_extra_model_call(
    review_database: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = execution_module.derive_shot_plan

    def lossy(bible, script):  # type: ignore[no-untyped-def]
        plan = real(bible, script)
        plan["shots"][1]["subject"] = "generic pet"
        return plan

    monkeypatch.setattr(execution_module, "derive_shot_plan", lossy)

    adapter, result, repository = _run_full(review_database, tmp_path, monkeypatch)

    assert result.summary["status"] == "NeedsHuman"
    assert adapter.calls == 4  # the 4 pre-existing model stages only; derived stage adds none
    assert repository.package_for(JOB_ID) is None
    assert repository.handoff_for(JOB_ID) is None
    job = repository.get_job(JOB_ID)
    assert job.status.value == "NeedsHuman"
    assert job.failure_code == "CREATIVE_PROMPT_LOCK_MISSING"
    stage = review_database.fetchone(
        "SELECT status,quality_outcome,failure_code FROM creative_stage_runs "
        "WHERE creative_job_id=? AND stage_kind='shot_plan.v1'",
        (JOB_ID,),
    )
    assert stage is not None
    assert (stage["status"], stage["quality_outcome"], stage["failure_code"]) == (
        "NeedsHuman",
        "NEEDS_HUMAN",
        "CREATIVE_PROMPT_LOCK_MISSING",
    )


def test_goal_job_missing_goal_snapshot_stops_before_any_model_call(
    review_database: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _commit_with_policy(review_database)
    review_database.execute(
        "DELETE FROM creative_goal_source_sets WHERE creative_job_id=?", (JOB_ID,)
    )
    job = CreativeRepository(review_database).get_job(JOB_ID)
    assert job.project_key.startswith("goal-")
    payload = SimpleNamespace(
        creative_job_id=JOB_ID,
        source_set_digest=job.source_set_digest,
        creative_profile=job.creative_profile,
    )
    monkeypatch.setattr(CreativeTaskPayload, "from_task", classmethod(lambda cls, task: payload))

    class NoCallAdapter:
        calls = 0

        def run(self, profile, context, *, correction=None):  # type: ignore[no-untyped-def]
            self.calls += 1
            raise AssertionError("model must not run for an unmapped Goal job")

    adapter = NoCallAdapter()
    coordinator = CreativeIntelligenceCoordinator(
        database=review_database,
        queue=DiagnosticQueueRepository(review_database),
        repository=CreativeRepository(review_database),
        source_normalizer=CreativeSourceNormalizer(review_database),
        store=CreativeArtifactStore(RuntimePaths.from_root(tmp_path / "runtime")),
        adapter=adapter,
        configured_model_id="synthetic:no-call",
    )
    now = datetime.now(UTC)
    result = coordinator.handler(
        TaskRecord(
            task_id="synthetic-unmapped",
            task_type=coordinator.TASK_TYPE,
            status=TaskStatus.RUNNING,
            priority=0,
            payload={},
            attempt_count=1,
            max_attempts=1,
            timeout_seconds=60,
            created_at=now,
            updated_at=now,
        )
    )

    assert result.summary["status"] == "NeedsHuman"
    assert adapter.calls == 0
    final = CreativeRepository(review_database).get_job(JOB_ID)
    assert final.failure_code == "TRUSTED_STATE_FACTS_GOAL_LINK_MISSING"
    assert review_database.scalar(
        "SELECT COUNT(*) FROM creative_stage_runs WHERE creative_job_id=?", (JOB_ID,)
    ) == 0


def test_later_commit_without_policy_supersedes_the_opt_in(
    review_database: Database,
) -> None:
    """The ledger has no revoke/expiry column; a newer owner commit is the only withdrawal."""

    first = _commit_with_policy(review_database)
    job = CreativeRepository(review_database).get_job(JOB_ID)
    opt_in = load_trusted_pet_creative_binding(review_database, job).opt_in()
    assert verify_owner_commitment_in_ledger(review_database, opt_in) is True

    # Forge-resistance: any digest, actor or commitment drift is refused by the callback.
    assert not verify_owner_commitment_in_ledger(
        review_database, opt_in.model_copy(update={"review_digest": "e" * 64})
    )
    assert not verify_owner_commitment_in_ledger(
        review_database, opt_in.model_copy(update={"review_actor_id": "someone-else"})
    )
    assert not verify_owner_commitment_in_ledger(
        review_database, opt_in.model_copy(update={"commitment_id": "missing"})
    )

    review_database.execute(
        "UPDATE canonical_evidence SET captured_at='2000-01-01T00:00:00+00:00' "
        "WHERE evidence_id=?",
        (first,),
    )
    later = _commit_with_policy(review_database, None, key="owner-withdraws-policy")
    assert later != first
    assert verify_owner_commitment_in_ledger(review_database, opt_in) is False
    with pytest.raises(TrustedPetCreativeBindingError, match="TRUSTED_STORY_POLICY_NOT_SELECTED"):
        load_trusted_pet_creative_binding(
            review_database, CreativeRepository(review_database).get_job(JOB_ID)
        )
