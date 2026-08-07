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


def _insert_handoff_and_session(
    database: Database,
    *,
    handoff_id: str,
    session_id: str,
    request_digest: str,
    package_digest: str,
) -> None:
    now = "2026-08-07T16:00:00+00:00"
    database.execute(
        "INSERT INTO handoffs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, ?, ?, ?)",
        (
            handoff_id,
            "picotoopet-repo-maintenance-codex-v1",
            "artifact capture",
            "capture one approved text change",
            "approved",
            request_digest,
            package_digest,
            "{}",
            "{}",
            f"prepare:{handoff_id}",
            now,
            now,
            "2026-08-08T16:00:00+00:00",
        ),
    )
    database.execute(
        "INSERT INTO provider_sessions ("
        "session_id, handoff_id, provider, status, request_digest, package_digest, "
        "budget_json, idempotency_key, created_at, updated_at, preview_json"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            session_id,
            handoff_id,
            "codex",
            "returning",
            request_digest,
            package_digest,
            "{}",
            f"session:{session_id}",
            now,
            now,
            "{}",
        ),
    )


def test_provider_return_persists_immutable_artifact_before_reviewable_fact(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    handoff_id = "handoff-artifact-e2e"
    session_id = str(uuid4())
    request_digest = "a" * 64
    package_digest = "b" * 64
    base_commit = "c" * 40
    _insert_handoff_and_session(
        database,
        handoff_id=handoff_id,
        session_id=session_id,
        request_digest=request_digest,
        package_digest=package_digest,
    )

    store = ProviderReturnArtifactStore(tmp_path / "provider-returns")
    coordinator = ProviderExecutionCoordinator(
        queue=None,  # 此测试只覆盖本地 Return 收口，不触发队列。
        sessions=SimpleNamespace(database=database),
        repository=tmp_path,
        worktree_root=tmp_path / "worktrees",
        codex_executable=tmp_path / "codex",
        worker_id="artifact-test-worker",
        artifact_store=store,
    )
    payload = ProviderTaskPayload(
        session_id=session_id,
        handoff_id=handoff_id,
        request_digest=request_digest,
        package_digest=package_digest,
        base_commit=base_commit,
        objective="capture approved docs change",
        allowed_write=("docs",),
    )
    captured = CapturedProviderChanges(
        changes=(
            ProviderChangeInput(
                operation="add",
                path="docs/accepted.txt",
                result_text="review me\n",
            ),
        ),
        review_diff="--- a/docs/accepted.txt\n+++ b/docs/accepted.txt\n+review me\n",
    )

    record = coordinator._persist_return(payload, captured, ())

    row = database.fetchone(
        "SELECT * FROM provider_return_artifacts WHERE return_id = ?",
        (record.return_id,),
    )
    assert row is not None
    assert row["session_id"] == session_id
    assert row["handoff_id"] == handoff_id
    assert row["base_commit"] == base_commit
    assert row["artifact_status"] == "reviewable"
    assert row["changed_file_count"] == 1
    assert row["payload_bytes"] == len(b"review me\n")
    assert len(row["change_set_digest"]) == 64
    assert len(row["review_diff_digest"]) == 64

    loaded = store.load(
        record.return_id,
        expected_change_set_digest=row["change_set_digest"],
    )
    assert loaded.changes[0].path == "docs/accepted.txt"
    assert loaded.review_diff.endswith("+review me\n")

    return_row = database.fetchone("SELECT preview_json FROM returns WHERE return_id = ?", (record.return_id,))
    assert return_row is not None
    preview = json.loads(return_row["preview_json"])
    assert preview["changed_file_count"] == 1
    database.close()
