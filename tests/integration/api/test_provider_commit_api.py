from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths


def make_client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    """创建使用临时 SQLite/runtime 的已配对 API 客户端。"""

    token = "0123456789abcdef0123456789abcdef"
    settings = AppSettings(
        paths=RuntimePaths.from_root(tmp_path / "runtime"),
        api_token=token,
    )
    return TestClient(create_app(settings)), {"Authorization": f"Bearer {token}"}


def seed_adoption_candidate(
    client: TestClient,
    *,
    status: str,
    suffix: str,
) -> tuple[str, str, str, str, str]:
    """直接写入一个最小但满足外键的 Provider/Adoption 事实链。"""

    database = client.app.state.services.database
    now = datetime.now(UTC).isoformat()
    handoff_id = f"handoff-commit-{suffix}"
    return_id = f"return-commit-{suffix}"
    session_id = str(uuid4())
    candidate_id = str(uuid4())
    base_commit = "a" * 40
    change_set_digest = "b" * 64
    request_digest = "c" * 64
    package_digest = "d" * 64

    database.execute(
        "INSERT INTO handoffs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, ?, ?, ?)",
        (
            handoff_id,
            "picotoopet-repo-maintenance-codex-v1",
            "commit fixture",
            "commit fixture objective",
            "approved",
            request_digest,
            package_digest,
            "{}",
            "{}",
            f"prepare-commit-{suffix}",
            now,
            now,
            "2026-08-08T23:59:59+00:00",
        ),
    )
    database.execute(
        "INSERT INTO returns VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)",
        (
            return_id,
            handoff_id,
            "contract_validated",
            "codex",
            request_digest,
            package_digest,
            "e" * 64,
            1,
            1,
            "[]",
            "{}",
            f"return-commit-key-{suffix}",
            now,
            now,
        ),
    )
    database.execute(
        "INSERT INTO provider_sessions ("
        "session_id, handoff_id, provider, status, request_digest, package_digest, "
        "budget_json, changed_file_count, return_id, idempotency_key, created_at, "
        "updated_at, finished_at, preview_json"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            session_id,
            handoff_id,
            "codex",
            "ready_for_review",
            request_digest,
            package_digest,
            "{}",
            1,
            return_id,
            f"session-commit-{suffix}",
            now,
            now,
            now,
            "{}",
        ),
    )
    database.execute(
        "INSERT INTO provider_adoption_candidates ("
        "candidate_id, session_id, return_id, status, base_commit, change_set_digest, "
        "changed_file_count, validation_json, failure_code, idempotency_key, created_at, "
        "updated_at, finished_at, preview_json"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)",
        (
            candidate_id,
            session_id,
            return_id,
            status,
            base_commit,
            change_set_digest,
            1,
            '["change_set_replayed","git_diff_check"]',
            f"adoption-commit-{suffix}",
            now,
            now,
            now if status == "adoption_ready" else None,
            "{}",
        ),
    )
    return candidate_id, session_id, return_id, base_commit, change_set_digest


def test_commit_prepare_is_bodyless_idempotent_and_digest_bound(tmp_path: Path) -> None:
    """API 只能从 adoption_ready 创建一次固定审批，不能接受自由提交参数。"""

    client, headers = make_client(tmp_path)
    with client:
        candidate_id, session_id, return_id, base_commit, digest = seed_adoption_candidate(
            client,
            status="adoption_ready",
            suffix="ready",
        )
        request_headers = {**headers, "Idempotency-Key": "commit-prepare-ready"}
        prepared = client.post(
            f"/api/v1/provider-adoption-candidates/{candidate_id}/commit/prepare",
            headers=request_headers,
        )
        replay = client.post(
            f"/api/v1/provider-adoption-candidates/{candidate_id}/commit/prepare",
            headers=request_headers,
        )
        rejected_body = client.post(
            f"/api/v1/provider-adoption-candidates/{candidate_id}/commit/prepare",
            headers={**headers, "Idempotency-Key": "commit-prepare-body"},
            json={
                "message": "arbitrary",
                "author": "attacker",
                "ref": "refs/heads/main",
                "path": "../escape",
                "command": "git push",
            },
        )

        assert prepared.status_code == 200
        body = prepared.json()
        assert replay.json() == body
        assert body["status"] == "waiting_approval"
        assert body["adoption_candidate_id"] == candidate_id
        assert body["session_id"] == session_id
        assert body["return_id"] == return_id
        assert body["base_commit"] == base_commit
        assert body["change_set_digest"] == digest
        assert body["local_ref"] == (
            f"refs/picotoopet/commit-candidates/{body['commit_candidate_id']}"
        )
        assert body["message_preview"] == (
            f"PicotooPet adoption candidate {body['commit_candidate_id']}"
        )
        assert rejected_body.status_code == 422

        approval = client.app.state.services.database.fetchone(
            "SELECT status, scope_json FROM approvals WHERE approval_id = ?",
            (body["approval_id"],),
        )
        assert approval is not None
        assert approval["status"] == "pending"
        scope = json.loads(approval["scope_json"])
        assert scope == {
            "action": "provider.commit.create-v1",
            "adoption_candidate_id": candidate_id,
            "base_commit": base_commit,
            "change_set_digest": digest,
            "commit_candidate_id": body["commit_candidate_id"],
            "local_ref": body["local_ref"],
            "message_digest": body["message_digest"],
            "return_id": return_id,
            "session_id": session_id,
        }

        forbidden = {"message", "author", "email", "branch", "remote", "command", "path", "patch"}
        assert forbidden.isdisjoint(body)


def test_commit_prepare_rejects_non_ready_candidate_and_requires_auth(tmp_path: Path) -> None:
    """非 adoption_ready 或未认证请求都不能形成 Commit Candidate。"""

    client, headers = make_client(tmp_path)
    with client:
        candidate_id, *_ = seed_adoption_candidate(
            client,
            status="validating",
            suffix="not-ready",
        )
        endpoint = f"/api/v1/provider-adoption-candidates/{candidate_id}/commit/prepare"
        not_ready = client.post(
            endpoint,
            headers={**headers, "Idempotency-Key": "commit-not-ready"},
        )
        unauthenticated = client.post(
            endpoint,
            headers={"Idempotency-Key": "commit-unauthenticated"},
        )

    assert not_ready.status_code == 400
    assert not_ready.json()["error"]["code"] == "COMMIT_ADOPTION_NOT_READY"
    assert unauthenticated.status_code in {401, 403}
