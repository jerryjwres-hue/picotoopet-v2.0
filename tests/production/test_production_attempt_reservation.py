from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from uuid import uuid4

from picotoopet_core.db.database import Database
from picotoopet_core.production.models import (
    ProductionHeartbeatRequest,
    ProductionPackageRecord,
    ProductionPlan,
    ProductionTaskCommitRequest,
    ProductionTaskAttemptRequest,
    ProductionTaskPlan,
)
from picotoopet_core.production.repository import ProductionRepository
from picotoopet_core.production.service import ProductionService


def _service(tmp_path: Path) -> tuple[ProductionService, ProductionRepository, str, str]:
    # ── Durable Core fixture with one executable task ────────────────────────
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    repository = ProductionRepository(database)
    package_id = str(uuid4())
    job = repository.create_job(
        production_job_id=str(uuid4()),
        creative_package_id=package_id,
        creative_package_digest="a" * 64,
        project_key="pet-dryer-us",
        production_profile="production.comfyui.v1",
        idempotency_key="attempt-reservation",
    )
    task = ProductionTaskPlan(
        production_task_id=str(uuid4()),
        shot_id="shot-001",
        order=1,
        render_intent="GENERATIVE_VIDEO",
        execution_disposition="Executable",
        workflow_id="comfy.wan22.ti2v5b.t2v.v1",
        positive_prompt="compact pet dryer demonstration",
        negative_prompt_policy_id="wan22.safe-negative.v1",
        seed=1234,
        width=832,
        height=480,
        fps=24,
        frame_count=81,
    )
    repository.save_plan(
        job.production_job_id,
        ProductionPlan(
            schema_version="1.0",
            production_profile="production.comfyui.v1",
            production_job_id=job.production_job_id,
            creative_package_id=package_id,
            creative_package_digest="a" * 64,
            project_key="pet-dryer-us",
            tasks=[task],
        ),
        "b" * 64,
    )
    service = ProductionService(
        repository=repository,
        creative_repository=None,  # type: ignore[arg-type]  # attempt path is production-only.
        store=None,                # type: ignore[arg-type]  # attempt path writes no package.
    )
    return service, repository, job.production_job_id, task.production_task_id


def test_reserve_then_bind_prompt_id_consumes_only_one_attempt(tmp_path: Path) -> None:
    service, repository, job_id, task_id = _service(tmp_path)
    claim = service.claim(job_id, "pc-gpu-1")

    reserved = service.mark_attempt(
        job_id,
        task_id,
        ProductionTaskAttemptRequest(
            executor_id="pc-gpu-1",
            lease_token=claim.lease_token,
            comfy_prompt_id=None,
        ),
    )
    assert reserved.attempt_count == 1
    assert reserved.comfy_prompt_id is None

    bound = service.mark_attempt(
        job_id,
        task_id,
        ProductionTaskAttemptRequest(
            executor_id="pc-gpu-1",
            lease_token=claim.lease_token,
            comfy_prompt_id="prompt-1",
        ),
    )
    assert bound.attempt_count == 1
    assert bound.comfy_prompt_id == "prompt-1"
    assert repository.database.scalar(
        "SELECT COUNT(*) FROM production_attempts WHERE production_task_id=?",
        (task_id,),
    ) == 1
    assert repository.database.scalar(
        "SELECT comfy_prompt_id FROM production_attempts WHERE production_task_id=? AND attempt_number=1",
        (task_id,),
    ) == "prompt-1"

def _expire_job_lease(repository: ProductionRepository, job_id: str) -> None:
    # ── Deterministic abandoned worker; no real GPU or elapsed-time sleep. ──
    repository.database.execute(
        "UPDATE production_jobs SET lease_expires_at=? WHERE production_job_id=?",
        ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), job_id),
    )


def _attempt_request(executor: str, lease_token: str, prompt: str | None = None):
    # ── Keep the executor/token pairing exact across retries. ───────────────
    return ProductionTaskAttemptRequest(
        executor_id=executor, lease_token=lease_token, comfy_prompt_id=prompt
    )


def test_bound_attempt_two_reclaim_history_commit_and_no_third_gpu(tmp_path: Path) -> None:
    service, repository, job_id, task_id = _service(tmp_path)
    first = service.claim(job_id, "gpu-old")
    service.mark_attempt(job_id, task_id, _attempt_request("gpu-old", first.lease_token))
    service.mark_attempt(
        job_id, task_id, _attempt_request("gpu-old", first.lease_token, "prompt-1")
    )
    # ── Retryable failed first prompt consumes the only remaining attempt. ──
    reserved_second = service.mark_attempt(
        job_id, task_id, _attempt_request("gpu-old", first.lease_token)
    )
    assert reserved_second.attempt_count == 2
    assert reserved_second.comfy_prompt_id is None
    bound_second = service.mark_attempt(
        job_id, task_id, _attempt_request("gpu-old", first.lease_token, "prompt-2")
    )
    assert bound_second.comfy_prompt_id == "prompt-2"
    _expire_job_lease(repository, job_id)

    recovered = service.claim(job_id, "gpu-new")
    assert len(recovered.plan.tasks) == 1
    assert recovered.tasks[0].attempt_count == 2
    assert recovered.tasks[0].comfy_prompt_id == "prompt-2"
    assert service.heartbeat(
        job_id,
        ProductionHeartbeatRequest(
            executor_id="gpu-new", lease_token=recovered.lease_token
        ),
    ).lease_executor_id == "gpu-new"
    with pytest.raises(ValueError, match="PRODUCTION_ATTEMPT_BUDGET_EXHAUSTED"):
        service.mark_attempt(
            job_id, task_id, _attempt_request("gpu-new", recovered.lease_token)
        )
    request = ProductionTaskCommitRequest(
        executor_id="gpu-new", lease_token=recovered.lease_token,
        comfy_prompt_id="prompt-2", output_relpath="output/shot.webm",
        output_sha256="a" * 64, output_bytes=1024, mime_type="video/webm",
        width=832, height=480, frame_count=81, fps=24,
    )
    with pytest.raises(ValueError, match="PRODUCTION_PROMPT_ID_CONFLICT"):
        service.commit_task(
            job_id, task_id,
            request.model_copy(update={"comfy_prompt_id": "unknown-new-prompt"}),
        )
    # ── Preexisting package bypasses only irrelevant final archive fixture. ─
    repository.save_package(
        ProductionPackageRecord(
            production_package_id=str(uuid4()),
            production_job_id=job_id,
            creative_package_id=repository.get_job(job_id).creative_package_id,
            plan_digest="b" * 64, package_digest="c" * 64,
            package_relpath="output/finished.zip", manifest={},
            quality_outcome="PASS", created_at=datetime.now(UTC),
        )
    )
    committed = service.commit_task(job_id, task_id, request)
    assert committed.status.value == "Succeeded"
    assert committed.attempt_count == 2
    assert repository.get_job(job_id).status.value == "production_ready"
    assert repository.database.scalar(
        "SELECT COUNT(*) FROM production_attempts WHERE production_task_id=?",
        (task_id,),
    ) == 2


def test_unknown_unbound_external_post_cannot_reclaim_or_leak_lease(
    tmp_path: Path,
) -> None:
    service, repository, job_id, task_id = _service(tmp_path)
    first = service.claim(job_id, "gpu-old")
    service.mark_attempt(job_id, task_id, _attempt_request("gpu-old", first.lease_token))
    _expire_job_lease(repository, job_id)
    with pytest.raises(ValueError, match="PRODUCTION_PROMPT_RECOVERY_UNVERIFIED"):
        service.claim(job_id, "gpu-new")
    assert repository.get_job(job_id).lease_executor_id == "gpu-old"
    assert repository.get_task(job_id, task_id).attempt_count == 1


def test_second_unbound_attempt_is_not_authorized_to_repost(tmp_path: Path) -> None:
    service, repository, job_id, task_id = _service(tmp_path)
    first = service.claim(job_id, "gpu-old")
    service.mark_attempt(job_id, task_id, _attempt_request("gpu-old", first.lease_token))
    service.mark_attempt(
        job_id, task_id, _attempt_request("gpu-old", first.lease_token, "prompt-1")
    )
    service.mark_attempt(job_id, task_id, _attempt_request("gpu-old", first.lease_token))
    _expire_job_lease(repository, job_id)
    with pytest.raises(ValueError, match="PRODUCTION_PROMPT_RECOVERY_UNVERIFIED"):
        service.claim(job_id, "gpu-new")
    assert repository.database.scalar(
        "SELECT COUNT(*) FROM production_attempts WHERE production_task_id=?",
        (task_id,),
    ) == 2


def test_claim_revalidates_bound_prompt_atomically_after_stale_preflight_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An intervening unknown POST must never gain a new lease through stale reads."""
    service, repository, job_id, task_id = _service(tmp_path)
    original = service.claim(job_id, "gpu-old")
    service.mark_attempt(job_id, task_id, _attempt_request("gpu-old", original.lease_token))
    service.mark_attempt(
        job_id, task_id, _attempt_request("gpu-old", original.lease_token, "known-prompt")
    )
    service.mark_attempt(job_id, task_id, _attempt_request("gpu-old", original.lease_token))
    service.mark_attempt(
        job_id, task_id, _attempt_request("gpu-old", original.lease_token, "known-second")
    )
    _expire_job_lease(repository, job_id)
    true_claim = repository.claim_job
    injected = False

    def race_then_claim(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal injected
        if not injected:
            injected = True
            # Simulate durable external prompt drift between the old P0
            # preflight read and the repository's serialized lease transaction.
            repository.database.execute(
                "UPDATE production_attempts SET comfy_prompt_id=? "
                "WHERE production_task_id=? AND attempt_number=2",
                ("unknown-post", task_id),
            )
        return true_claim(*args, **kwargs)

    monkeypatch.setattr(repository, "claim_job", race_then_claim)
    with pytest.raises(ValueError, match="PRODUCTION_PROMPT_RECOVERY_UNVERIFIED"):
        service.claim(job_id, "gpu-new")
    assert injected is True
    assert repository.get_job(job_id).lease_executor_id == "gpu-old"
    assert repository.get_task(job_id, task_id).comfy_prompt_id == "known-second"
    assert repository.database.scalar(
        "SELECT COUNT(*) FROM production_attempts WHERE production_task_id=?",
        (task_id,),
    ) == 2


def test_claim_rejects_terminal_change_before_lease_rotation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task becoming terminal at claim boundary must not lease a non-runnable job."""
    service, repository, job_id, task_id = _service(tmp_path)
    first = service.claim(job_id, "gpu-old")
    _expire_job_lease(repository, job_id)
    original = repository.claim_job

    def terminal_then_claim(*args, **kwargs):  # type: ignore[no-untyped-def]
        repository.database.execute(
            "UPDATE production_tasks SET status='Failed' WHERE production_task_id=?",
            (task_id,),
        )
        return original(*args, **kwargs)

    monkeypatch.setattr(repository, "claim_job", terminal_then_claim)
    with pytest.raises(ValueError, match="PRODUCTION_TASK_TERMINAL_STATE"):
        service.claim(job_id, "gpu-new")
    assert repository.get_job(job_id).lease_executor_id == "gpu-old"
    assert repository.get_task(job_id, task_id).status.value == "Failed"
    assert repository.get_job(job_id).lease_token_digest is not None
    assert first.lease_token != ""
