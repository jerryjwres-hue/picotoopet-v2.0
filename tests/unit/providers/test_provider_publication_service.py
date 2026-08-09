from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from picotoopet_core.db.database import Database
from picotoopet_core.handoffs.approvals import HandoffApprovalService
from picotoopet_core.providers.publication_models import ProviderPublicationStatus
from picotoopet_core.providers.publication_service import (
    ProviderPublicationError,
    ProviderPublicationService,
)
from picotoopet_core.queue.diagnostic_repository import DiagnosticQueueRepository


def seed_commit_ready(
    database: Database,
    approvals: HandoffApprovalService,
    *,
    commit_status: str = "commit_ready",
) -> tuple[str, str, str, str]:
    now = datetime.now(UTC)
    handoff_id = str(uuid4())
    session_id = str(uuid4())
    adoption_id = str(uuid4())
    commit_id = str(uuid4())
    commit_approval_id = str(uuid4())
    base_commit = "a" * 40
    commit_sha = "b" * 40
    change_digest = "c" * 64
    repo_url = "https://github.com/jerryjwres-hue/picotoopet-v2.0"
    base_ref = "feature/verified-baseline"
    handoff_preview = {
        "handoff_id": handoff_id,
        "repo_url": repo_url,
        "base_ref": base_ref,
        "base_commit": base_commit,
    }
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO handoffs (handoff_id, template_id, title, objective_summary, status, "
            "request_digest, package_digest, manifest_json, preview_json, approval_id, "
            "prepare_idempotency_key, approval_idempotency_key, created_at, updated_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, ?, ?, ?)",
            (
                handoff_id,
                "picotoopet-repo-maintenance-codex-v1",
                "publication test",
                "publication test",
                "approved",
                "d" * 64,
                "e" * 64,
                "{}",
                json.dumps(handoff_preview),
                f"handoff-{handoff_id}",
                now.isoformat(),
                now.isoformat(),
                (now + timedelta(hours=1)).isoformat(),
            ),
        )
        connection.execute(
            "INSERT INTO provider_sessions (session_id, handoff_id, provider, status, request_digest, "
            "package_digest, budget_json, turns_used, elapsed_seconds, changed_file_count, return_id, "
            "failure_code, provider_usage_unknown, idempotency_key, created_at, updated_at, finished_at, "
            "preview_json) VALUES (?, ?, 'codex', 'ready_for_review', ?, ?, '{}', 1, 1, 1, NULL, "
            "NULL, 1, ?, ?, ?, ?, '{}')",
            (
                session_id,
                handoff_id,
                "d" * 64,
                "e" * 64,
                f"session-{session_id}",
                now.isoformat(),
                now.isoformat(),
                now.isoformat(),
            ),
        )
        connection.execute(
            "INSERT INTO provider_adoption_candidates (candidate_id, session_id, return_id, status, "
            "base_commit, change_set_digest, changed_file_count, validation_json, failure_code, "
            "idempotency_key, created_at, updated_at, finished_at, preview_json) "
            "VALUES (?, ?, ?, 'adoption_ready', ?, ?, 1, '[]', NULL, ?, ?, ?, ?, '{}')",
            (
                adoption_id,
                session_id,
                f"return-{adoption_id}",
                base_commit,
                change_digest,
                f"adoption-{adoption_id}",
                now.isoformat(),
                now.isoformat(),
                now.isoformat(),
            ),
        )
        connection.execute(
            "INSERT INTO approvals (approval_id, task_id, approval_type, scope_json, status, token_hash, "
            "requested_by, expires_at, requested_at, resolved_by, resolved_at, decision_reason) "
            "VALUES (?, NULL, 'provider.commit.create-v1', '{}', 'Approved', 'hash', 'test', ?, ?, "
            "'owner', ?, 'test')",
            (
                commit_approval_id,
                (now + timedelta(hours=1)).isoformat(),
                now.isoformat(),
                now.isoformat(),
            ),
        )
        connection.execute(
            "INSERT INTO provider_commit_candidates (commit_candidate_id, adoption_candidate_id, "
            "session_id, return_id, status, base_commit, change_set_digest, tree_sha, commit_sha, "
            "local_ref, approval_id, idempotency_key, validation_json, failure_code, author_time_utc, "
            "created_at, updated_at, finished_at, preview_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', NULL, ?, ?, ?, ?, '{}')",
            (
                commit_id,
                adoption_id,
                session_id,
                f"return-{adoption_id}",
                commit_status,
                base_commit,
                change_digest,
                "f" * 40,
                commit_sha,
                f"refs/picotoopet/commit-candidates/{commit_id}",
                commit_approval_id,
                f"commit-{commit_id}",
                now.isoformat(),
                now.isoformat(),
                now.isoformat(),
                now.isoformat(),
            ),
        )
    return commit_id, repo_url, base_ref, commit_sha


def make_service(tmp_path):
    database = Database(tmp_path / "db.sqlite3")
    database.open()
    database.apply_migrations()
    approvals = HandoffApprovalService(database, DiagnosticQueueRepository(database))
    return database, approvals, ProviderPublicationService(database, approvals)


def test_prepare_derives_repo_and_base_only_from_handoff_provenance(tmp_path) -> None:
    database, approvals, service = make_service(tmp_path)
    try:
        commit_id, repo_url, base_ref, commit_sha = seed_commit_ready(database, approvals)
        candidate = service.prepare(commit_id, idempotency_key="publish-test-1")

        assert candidate.status is ProviderPublicationStatus.WAITING_APPROVAL
        assert candidate.repo_url == repo_url
        assert candidate.repository_slug == "jerryjwres-hue/picotoopet-v2.0"
        assert candidate.base_ref == base_ref
        assert candidate.base_commit == "a" * 40
        assert candidate.commit_sha == commit_sha
        assert candidate.remote_ref == (
            f"refs/heads/picotoopet/commit-candidates/{candidate.publication_candidate_id}"
        )
        approval = database.fetchone(
            "SELECT approval_type, scope_json FROM approvals WHERE approval_id = ?",
            (candidate.approval_id,),
        )
        assert approval is not None
        assert approval["approval_type"] == "provider.publish.pr-create-v1"
        scope = json.loads(approval["scope_json"])
        assert scope["base_ref"] == base_ref
        assert scope["commit_sha"] == commit_sha
        assert scope["draft"] is True
    finally:
        database.close()


def test_prepare_rejects_commit_that_is_not_commit_ready(tmp_path) -> None:
    database, approvals, service = make_service(tmp_path)
    try:
        commit_id, *_ = seed_commit_ready(database, approvals, commit_status="queued")
        with pytest.raises(ProviderPublicationError, match="PUBLICATION_COMMIT_NOT_READY"):
            service.prepare(commit_id, idempotency_key="publish-test-2")
    finally:
        database.close()
