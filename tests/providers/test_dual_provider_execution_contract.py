from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from picotoopet_core.db.database import Database
from picotoopet_core.providers.artifact_store import ProviderReturnArtifactStore
from picotoopet_core.providers.change_set import ProviderChangeInput
from picotoopet_core.providers.execution import ProviderExecutionCoordinator, ProviderTaskPayload
from picotoopet_core.worker.codex_worktree import CapturedProviderChanges


def _payload(provider: str) -> ProviderTaskPayload:
    return ProviderTaskPayload(
        provider=provider,
        session_id=str(uuid4()),
        handoff_id=f"handoff-{provider}",
        request_digest="a" * 64,
        package_digest="b" * 64,
        base_commit="c" * 40,
        objective="perform only the approved bounded maintenance task",
        allowed_write=("docs",),
    )


def test_execution_exposes_two_fixed_task_types_and_provider_bound_payload() -> None:
    assert ProviderExecutionCoordinator.CODEX_TASK_TYPE == "provider.codex.handoff-v1"
    assert (
        ProviderExecutionCoordinator.CLAUDE_CODE_TASK_TYPE
        == "provider.claude-code.handoff-v1"
    )
    assert ProviderExecutionCoordinator.TASK_TYPE == ProviderExecutionCoordinator.CODEX_TASK_TYPE
    assert ProviderExecutionCoordinator.task_type_for("codex") == (
        ProviderExecutionCoordinator.CODEX_TASK_TYPE
    )
    assert ProviderExecutionCoordinator.task_type_for("claude_code") == (
        ProviderExecutionCoordinator.CLAUDE_CODE_TASK_TYPE
    )
    assert _payload("codex").provider == "codex"
    assert _payload("claude_code").provider == "claude_code"


def test_coordinator_accepts_both_fixed_executables_without_extra_authority(tmp_path: Path) -> None:
    coordinator = ProviderExecutionCoordinator(
        queue=None,
        sessions=SimpleNamespace(),
        repository=tmp_path,
        worktree_root=tmp_path / "worktrees",
        codex_executable=tmp_path / "codex",
        claude_code_executable=tmp_path / "claude",
        worker_id="dual-provider-test",
        artifact_store=ProviderReturnArtifactStore(tmp_path / "returns"),
    )

    assert coordinator.codex_executable == tmp_path / "codex"
    assert coordinator.claude_code_executable == tmp_path / "claude"


def test_claude_return_uses_same_immutable_return_lane_and_provider_fact(tmp_path: Path) -> None:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    payload = _payload("claude_code")
    now = "2026-08-19T03:15:00+00:00"
    database.execute(
        "INSERT INTO handoffs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, ?, ?, ?)",
        (
            payload.handoff_id,
            "picotoopet-repo-maintenance-claude-code-v1",
            "claude artifact capture",
            payload.objective,
            "approved",
            payload.request_digest,
            payload.package_digest,
            "{}",
            "{}",
            f"prepare:{payload.handoff_id}",
            now,
            now,
            "2026-08-20T03:15:00+00:00",
        ),
    )
    database.execute(
        "INSERT INTO provider_sessions ("
        "session_id, handoff_id, provider, status, request_digest, package_digest, "
        "budget_json, idempotency_key, created_at, updated_at, preview_json"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            payload.session_id,
            payload.handoff_id,
            "claude_code",
            "returning",
            payload.request_digest,
            payload.package_digest,
            "{}",
            f"session:{payload.session_id}",
            now,
            now,
            "{}",
        ),
    )
    coordinator = ProviderExecutionCoordinator(
        queue=None,
        sessions=SimpleNamespace(database=database),
        repository=tmp_path,
        worktree_root=tmp_path / "worktrees",
        codex_executable=tmp_path / "codex",
        claude_code_executable=tmp_path / "claude",
        worker_id="dual-provider-return-test",
        artifact_store=ProviderReturnArtifactStore(tmp_path / "provider-returns"),
    )
    captured = CapturedProviderChanges(
        changes=(
            ProviderChangeInput(
                operation="add",
                path="docs/claude-accepted.txt",
                result_text="review me\n",
            ),
        ),
        review_diff=(
            "--- a/docs/claude-accepted.txt\n"
            "+++ b/docs/claude-accepted.txt\n"
            "+review me\n"
        ),
    )

    record = coordinator._persist_return(payload, captured, ())

    assert record.provider == "claude_code"
    row = database.fetchone(
        "SELECT provider, preview_json FROM returns WHERE return_id = ?",
        (record.return_id,),
    )
    assert row is not None
    assert row["provider"] == "claude_code"
    assert json.loads(row["preview_json"])["provider"] == "claude_code"
    artifact = database.fetchone(
        "SELECT artifact_status FROM provider_return_artifacts WHERE return_id = ?",
        (record.return_id,),
    )
    assert artifact is not None
    assert artifact["artifact_status"] == "reviewable"
    database.close()
