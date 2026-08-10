from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from picotoopet_core.db.database import Database
from picotoopet_core.domain.enums import ApprovalStatus
from picotoopet_core.handoffs.approvals import HandoffApprovalService
from picotoopet_core.providers.commit_models import ProviderCommitStatus
from picotoopet_core.providers.commit_service import ProviderCommitService
from picotoopet_core.providers.publication_models import ProviderPublicationStatus
from picotoopet_core.providers.publication_service import ProviderPublicationService
from picotoopet_core.queue.diagnostic_repository import DiagnosticQueueRepository


def seed_commit_ready(database: Database) -> str:
    now = datetime.now(UTC)
    handoff_id = str(uuid4())
    session_id = str(uuid4())
    adoption_id = str(uuid4())
    commit_id = str(uuid4())
    commit_approval_id = str(uuid4())
    return_id = f"return-{adoption_id}"
    base_commit = "a" * 40
    commit_sha = "b" * 40
    change_digest = "c" * 64
    handoff_preview = {
        "handoff_id": handoff_id,
        "repo_url": "https://github.com/jerryjwres-hue/picotoopet-v2.0",
        "base_ref": "feature/verified-baseline",
        "base_commit": base_commit,
    }
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO handoffs (handoff_id, template_id, title, objective_summary, status, "
            "request_digest, package_digest, manifest_json, preview_json, approval_id, "
            "prepare_idempotency_key, approval_idempotency_key, created_at, updated_at, expires_at) "
            "VALUES (?, 'picotoopet-repo-maintenance-codex-v1', 'terminal approval test', "
            "'terminal approval test', 'approved', ?, ?, '{}', ?, NULL, ?, NULL, ?, ?, ?)",
            (
                handoff_id,
                "d" * 64,
                "e" * 64,
                json.dumps(handoff_preview),
                f"handoff-{handoff_id}",
                now.isoformat(),
                now.isoformat(),
                (now + timedelta(hours=1)).isoformat(),
            ),
        )
        connection.execute(
            "INSERT INTO returns (return_id, handoff_id, status, provider, request_digest, "
            "package_digest, manifest_digest, changed_file_count, event_count, "
            "validation_checks_json, preview_json, quarantine_code, idempotency_key, "
            "created_at, updated_at) VALUES (?, ?, 'validated', 'codex', ?, ?, ?, 1, 1, "
            "'[]', '{}', NULL, ?, ?, ?)",
            (
                return_id,
                handoff_id,
                "d" * 64,
                "e" * 64,
                "f" * 64,
                f"return-{return_id}",
                now.isoformat(),
                now.isoformat(),
            ),
        )
        connection.execute(
            "INSERT INTO provider_sessions (session_id, handoff_id, provider, status, "
            "request_digest, package_digest, budget_json, turns_used, elapsed_seconds, "
            "changed_file_count, return_id, failure_code, provider_usage_unknown, "
            "idempotency_key, created_at, updated_at, finished_at, preview_json) "
            "VALUES (?, ?, 'codex', 'ready_for_review', ?, ?, '{}', 1, 1, 1, ?, NULL, 1, "
            "?, ?, ?, ?, '{}')",
            (
                session_id,
                handoff_id,
                "d" * 64,
                "e" * 64,
                return_id,
                f"session-{session_id}",
                now.isoformat(),
                now.isoformat(),
                now.isoformat(),
            ),
        )
        connection.execute(
            "INSERT INTO provider_adoption_candidates (candidate_id, session_id, return_id, "
            "status, base_commit, change_set_digest, changed_file_count, validation_json, "
            "failure_code, idempotency_key, created_at, updated_at, finished_at, preview_json) "
            "VALUES (?, ?, ?, 'adoption_ready', ?, ?, 1, '[]', NULL, ?, ?, ?, ?, '{}')",
            (
                adoption_id,
                session_id,
                return_id,
                base_commit,
                change_digest,
                f"adoption-{adoption_id}",
                now.isoformat(),
                now.isoformat(),
                now.isoformat(),
            ),
        )
        connection.execute(
            "INSERT INTO approvals (approval_id, task_id, approval_type, scope_json, status, "
            "token_hash, requested_by, expires_at, requested_at, resolved_by, resolved_at, "
            "decision_reason) VALUES (?, NULL, 'provider.commit.create-v1', '{}', ?, 'hash', "
            "'test', ?, ?, 'owner', ?, 'test')",
            (
                commit_approval_id,
                ApprovalStatus.APPROVED.value,
                (now + timedelta(hours=1)).isoformat(),
                now.isoformat(),
                now.isoformat(),
            ),
        )
        connection.execute(
            "INSERT INTO provider_commit_candidates (commit_candidate_id, adoption_candidate_id, "
            "session_id, return_id, status, base_commit, change_set_digest, tree_sha, commit_sha, "
            "local_ref, approval_id, idempotency_key, validation_json, failure_code, "
            "author_time_utc, created_at, updated_at, finished_at, preview_json) "
            "VALUES (?, ?, ?, ?, 'commit_ready', ?, ?, ?, ?, ?, ?, ?, '[]', NULL, ?, ?, ?, ?, '{}')",
            (
                commit_id,
                adoption_id,
                session_id,
                return_id,
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
    return commit_id


def make_services(tmp_path):
    database = Database(tmp_path / "db.sqlite3")
    database.open()
    database.apply_migrations()
    approvals = HandoffApprovalService(database, DiagnosticQueueRepository(database))
    return (
        database,
        ProviderCommitService(database, approvals),
        ProviderPublicationService(database, approvals),
    )


@pytest.mark.parametrize(
    ("approval_status", "expected_status", "failure_code"),
    [
        (
            ApprovalStatus.REJECTED.value,
            ProviderCommitStatus.REJECTED,
            "COMMIT_APPROVAL_REJECTED",
        ),
        (
            ApprovalStatus.EXPIRED.value,
            ProviderCommitStatus.CANCELLED,
            "COMMIT_APPROVAL_EXPIRED",
        ),
    ],
)
def test_commit_read_reconciles_terminal_approval_without_worker(
    tmp_path,
    approval_status: str,
    expected_status: ProviderCommitStatus,
    failure_code: str,
) -> None:
    database, commit_service, _publication_service = make_services(tmp_path)
    try:
        commit_id = seed_commit_ready(database)
        row = database.fetchone(
            "SELECT approval_id FROM provider_commit_candidates WHERE commit_candidate_id = ?",
            (commit_id,),
        )
        assert row is not None
        database.execute(
            "UPDATE provider_commit_candidates SET status = ?, failure_code = NULL, "
            "finished_at = NULL WHERE commit_candidate_id = ?",
            (ProviderCommitStatus.WAITING_APPROVAL.value, commit_id),
        )
        database.execute(
            "UPDATE approvals SET status = ? WHERE approval_id = ?",
            (approval_status, row["approval_id"]),
        )

        candidate = commit_service.get_candidate(commit_id)

        assert candidate.status is expected_status
        assert candidate.failure_code == failure_code
        assert candidate.finished_at is not None
    finally:
        database.close()


@pytest.mark.parametrize(
    ("approval_status", "expected_status", "failure_code"),
    [
        (
            ApprovalStatus.REJECTED.value,
            ProviderPublicationStatus.REJECTED,
            "PUBLICATION_APPROVAL_REJECTED",
        ),
        (
            ApprovalStatus.EXPIRED.value,
            ProviderPublicationStatus.CANCELLED,
            "PUBLICATION_APPROVAL_EXPIRED",
        ),
    ],
)
def test_publication_read_reconciles_terminal_approval_without_worker(
    tmp_path,
    approval_status: str,
    expected_status: ProviderPublicationStatus,
    failure_code: str,
) -> None:
    database, _commit_service, publication_service = make_services(tmp_path)
    try:
        commit_id = seed_commit_ready(database)
        candidate = publication_service.prepare(
            commit_id,
            idempotency_key=f"publication-terminal-{approval_status}",
        )
        database.execute(
            "UPDATE approvals SET status = ? WHERE approval_id = ?",
            (approval_status, candidate.approval_id),
        )

        refreshed = publication_service.get_candidate(candidate.publication_candidate_id)

        assert refreshed.status is expected_status
        assert refreshed.failure_code == failure_code
        assert refreshed.finished_at is not None
    finally:
        database.close()
