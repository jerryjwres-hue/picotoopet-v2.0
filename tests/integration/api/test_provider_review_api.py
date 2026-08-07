from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.providers.artifact_store import ProviderReturnArtifactStore
from picotoopet_core.providers.change_set import ProviderChangeInput


def make_client(tmp_path: Path) -> tuple[TestClient, dict[str, str], RuntimePaths]:
    token = "0123456789abcdef0123456789abcdef"
    paths = RuntimePaths.from_root(tmp_path / "runtime")
    settings = AppSettings(paths=paths, api_token=token)
    return TestClient(create_app(settings)), {"Authorization": f"Bearer {token}"}, paths


def seed_review_session(
    client: TestClient,
    paths: RuntimePaths,
    *,
    with_artifact: bool,
    suffix: str,
) -> tuple[str, str, str]:
    database = client.app.state.services.database
    now = datetime.now(UTC).isoformat()
    session_id = str(uuid4())
    handoff_id = f"handoff-review-{suffix}"
    return_id = f"return-review-{suffix}"
    request_digest = "a" * 64
    package_digest = "b" * 64
    base_commit = "c" * 40
    database.execute(
        "INSERT INTO handoffs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, ?, ?, ?)",
        (
            handoff_id,
            "picotoopet-repo-maintenance-codex-v1",
            "review fixture",
            "review fixture objective",
            "approved",
            request_digest,
            package_digest,
            "{}",
            "{}",
            f"prepare-review-{suffix}",
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
            "d" * 64,
            1,
            1,
            "[]",
            "{}",
            f"return-review-key-{suffix}",
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
            f"session-review-{suffix}",
            now,
            now,
            now,
            "{}",
        ),
    )
    if with_artifact:
        store = ProviderReturnArtifactStore(paths.provider_returns_dir)
        artifact = store.write(
            return_id=return_id,
            base_commit=base_commit,
            changes=[
                ProviderChangeInput(
                    operation="add",
                    path="docs/review.txt",
                    result_text="reviewed change\n",
                )
            ],
            review_diff="--- a/docs/review.txt\n+++ b/docs/review.txt\n+reviewed change\n",
        )
        preview = {
            "return_id": return_id,
            "session_id": session_id,
            "handoff_id": handoff_id,
            "base_commit": base_commit,
            "change_set_digest": artifact.change_set_digest,
            "review_diff_digest": artifact.review_diff_digest,
            "changed_file_count": 1,
            "payload_bytes": artifact.payload_bytes,
            "artifact_status": "reviewable",
            "files": [
                {
                    "operation": "add",
                    "path": "docs/review.txt",
                    "size_bytes": len(b"reviewed change\n"),
                    "base_sha256": None,
                    "result_sha256": artifact.changes[0].result_sha256,
                }
            ],
            "created_at": now,
        }
        database.execute(
            "INSERT INTO provider_return_artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                return_id,
                session_id,
                handoff_id,
                base_commit,
                artifact.change_set_digest,
                artifact.review_diff_digest,
                1,
                artifact.payload_bytes,
                "reviewable",
                now,
                json.dumps(preview, separators=(",", ":")),
            ),
        )
    return session_id, handoff_id, return_id


def test_review_api_reads_bounded_diff_and_accepts_idempotently(tmp_path: Path) -> None:
    client, headers, paths = make_client(tmp_path)
    with client:
        session_id, _, return_id = seed_review_session(
            client,
            paths,
            with_artifact=True,
            suffix="accept",
        )
        review = client.get(f"/api/v1/provider-sessions/{session_id}/review", headers=headers)
        accepted = client.post(
            f"/api/v1/provider-sessions/{session_id}/review/accept",
            headers={**headers, "Idempotency-Key": "review-accept-key"},
        )
        replay = client.post(
            f"/api/v1/provider-sessions/{session_id}/review/accept",
            headers={**headers, "Idempotency-Key": "review-accept-key"},
        )
        candidates = client.get("/api/v1/provider-adoption-candidates?limit=100", headers=headers)

    assert review.status_code == 200
    body = review.json()
    assert body["review_status"] == "reviewable"
    assert body["return_id"] == return_id
    assert body["changed_file_count"] == 1
    assert body["files"][0]["path"] == "docs/review.txt"
    assert body["files"][0]["operation"] == "add"
    assert body["review_diff"].endswith("+reviewed change\n")
    assert accepted.status_code == 200
    assert accepted.json()["review_status"] == "accepted"
    assert accepted.json()["candidate_id"]
    assert replay.json() == accepted.json()
    assert len(candidates.json()) == 1
    assert candidates.json()[0]["candidate_id"] == accepted.json()["candidate_id"]
    assert candidates.json()[0]["status"] == "queued"


def test_review_reject_is_immutable_and_creates_no_candidate(tmp_path: Path) -> None:
    client, headers, paths = make_client(tmp_path)
    with client:
        session_id, _, _ = seed_review_session(
            client,
            paths,
            with_artifact=True,
            suffix="reject",
        )
        rejected = client.post(
            f"/api/v1/provider-sessions/{session_id}/review/reject",
            headers={**headers, "Idempotency-Key": "review-reject-key"},
        )
        reverse = client.post(
            f"/api/v1/provider-sessions/{session_id}/review/accept",
            headers={**headers, "Idempotency-Key": "review-reverse-key"},
        )
        candidates = client.get("/api/v1/provider-adoption-candidates?limit=100", headers=headers)

    assert rejected.status_code == 200
    assert rejected.json()["review_status"] == "rejected"
    assert rejected.json()["candidate_id"] is None
    assert reverse.status_code == 409
    assert reverse.json()["error"]["code"] == "ADOPTION_ALREADY_DECIDED"
    assert candidates.json() == []


def test_legacy_ready_for_review_without_artifact_is_readonly_history(tmp_path: Path) -> None:
    client, headers, paths = make_client(tmp_path)
    with client:
        session_id, _, _ = seed_review_session(
            client,
            paths,
            with_artifact=False,
            suffix="legacy",
        )
        review = client.get(f"/api/v1/provider-sessions/{session_id}/review", headers=headers)
        accepted = client.post(
            f"/api/v1/provider-sessions/{session_id}/review/accept",
            headers={**headers, "Idempotency-Key": "legacy-accept-key"},
        )

    assert review.status_code == 200
    assert review.json()["review_status"] == "legacy_no_artifact"
    assert review.json()["review_diff"] == ""
    assert review.json()["files"] == []
    assert accepted.status_code == 400
    assert accepted.json()["error"]["code"] == "ADOPTION_ARTIFACT_MISSING"


def test_review_mutations_reject_any_request_body(tmp_path: Path) -> None:
    client, headers, paths = make_client(tmp_path)
    with client:
        session_id, _, _ = seed_review_session(
            client,
            paths,
            with_artifact=True,
            suffix="body",
        )
        for action in ("accept", "reject"):
            response = client.post(
                f"/api/v1/provider-sessions/{session_id}/review/{action}",
                headers={**headers, "Idempotency-Key": f"review-body-{action}"},
                json={
                    "patch": "user supplied patch",
                    "path": "../escape",
                    "reason": "arbitrary",
                },
            )
            assert response.status_code == 422
