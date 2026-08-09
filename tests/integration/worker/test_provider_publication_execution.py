from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from picotoopet_core.db.database import Database
from picotoopet_core.domain.enums import ApprovalStatus, TaskStatus
from picotoopet_core.providers.publication_execution import (
    ProviderPublicationExecutionCoordinator,
)
from picotoopet_core.providers.publication_models import ProviderPublicationStatus
from picotoopet_core.providers.publication_service import ProviderPublicationService
from picotoopet_core.queue.diagnostic_repository import DiagnosticQueueRepository
from picotoopet_core.worker.runtime import WorkerRuntime
from picotoopet_core.worker.state import WorkerStateStore


def git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout.strip()


def make_git_fixture(tmp_path: Path) -> tuple[Path, Path, str, str]:
    repository = tmp_path / "repo"
    remote = tmp_path / "remote.git"
    repository.mkdir()
    git(repository, "init", "-b", "feature/verified-baseline")
    git(repository, "config", "user.name", "PicotooPet Test")
    git(repository, "config", "user.email", "test@picotoopet.invalid")
    (repository / "data.txt").write_text("base\n", encoding="utf-8")
    git(repository, "add", "data.txt")
    git(repository, "commit", "-m", "base")
    base_commit = git(repository, "rev-parse", "HEAD")
    (repository / "data.txt").write_text("candidate\n", encoding="utf-8")
    git(repository, "add", "data.txt")
    git(repository, "commit", "-m", "candidate")
    commit_sha = git(repository, "rev-parse", "HEAD")
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    git(
        repository,
        "push",
        str(remote),
        f"{base_commit}:refs/heads/feature/verified-baseline",
    )
    return repository, remote, base_commit, commit_sha


def make_fake_gh(tmp_path: Path, commit_sha: str) -> Path:
    executable = tmp_path / "fake-gh.py"
    executable.write_text(
        f"""#!/usr/bin/env python3
import json
import sys
from pathlib import Path

state = Path(__file__).with_name('fake-gh-state.json')
args = sys.argv[1:]
if args[:2] == ['auth', 'status']:
    raise SystemExit(0)
if args[:2] == ['pr', 'list']:
    print(state.read_text() if state.exists() else '[]')
    raise SystemExit(0)
if args[:2] == ['pr', 'create']:
    repo = args[args.index('--repo') + 1]
    base = args[args.index('--base') + 1]
    head = args[args.index('--head') + 1]
    if '--draft' not in args:
        raise SystemExit(72)
    rows = [{{
        'number': 77,
        'url': f'https://github.com/{{repo}}/pull/77',
        'isDraft': True,
        'baseRefName': base,
        'headRefName': head,
        'headRefOid': '{commit_sha}',
        'state': 'OPEN',
    }}]
    state.write_text(json.dumps(rows))
    print(rows[0]['url'])
    raise SystemExit(0)
raise SystemExit(91)
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


def seed_publication(
    database: Database,
    *,
    repo_url: str,
    base_commit: str,
    commit_sha: str,
) -> tuple[str, str]:
    now = datetime.now(UTC)
    handoff_id = str(uuid4())
    return_id = f"return-{uuid4()}"
    session_id = str(uuid4())
    adoption_id = str(uuid4())
    commit_id = str(uuid4())
    commit_approval_id = str(uuid4())
    publication_id = str(uuid4())
    publication_approval_id = str(uuid4())
    change_set_digest = "c" * 64
    remote_ref = ProviderPublicationService.remote_ref(publication_id)
    remote_branch = ProviderPublicationService.remote_branch(publication_id)
    body_facts = {
        "publication_candidate_id": publication_id,
        "commit_candidate_id": commit_id,
        "session_id": session_id,
        "handoff_id": handoff_id,
        "base_ref": "feature/verified-baseline",
        "base_commit": base_commit,
        "commit_sha": commit_sha,
        "change_set_digest": change_set_digest,
    }
    title_digest = ProviderPublicationService.pr_title_digest(publication_id, commit_sha)
    body_digest = ProviderPublicationService.pr_body_digest(**body_facts)
    scope = {
        "action": ProviderPublicationService.APPROVAL_TYPE,
        "publication_candidate_id": publication_id,
        "commit_candidate_id": commit_id,
        "session_id": session_id,
        "handoff_id": handoff_id,
        "commit_sha": commit_sha,
        "base_commit": base_commit,
        "change_set_digest": change_set_digest,
        "repo_url": repo_url,
        "repository_slug": "jerryjwres-hue/picotoopet-v2.0",
        "base_ref": "feature/verified-baseline",
        "remote_ref": remote_ref,
        "pr_title_digest": title_digest,
        "pr_body_digest": body_digest,
        "draft": True,
    }
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO handoffs (handoff_id, template_id, title, objective_summary, status, "
            "request_digest, package_digest, manifest_json, preview_json, approval_id, "
            "prepare_idempotency_key, approval_idempotency_key, created_at, updated_at, expires_at) "
            "VALUES (?, 'picotoopet-repo-maintenance-codex-v1', 'e2e', 'e2e', 'approved', ?, ?, '{}', "
            "'{}', NULL, ?, NULL, ?, ?, ?)",
            (
                handoff_id,
                "d" * 64,
                "e" * 64,
                f"handoff-{handoff_id}",
                now.isoformat(),
                now.isoformat(),
                (now + timedelta(hours=1)).isoformat(),
            ),
        )
        connection.execute(
            "INSERT INTO returns (return_id, handoff_id, status, provider, request_digest, package_digest, "
            "manifest_digest, changed_file_count, event_count, validation_checks_json, preview_json, "
            "quarantine_code, idempotency_key, created_at, updated_at) "
            "VALUES (?, ?, 'validated', 'codex', ?, ?, ?, 1, 1, '[]', '{}', NULL, ?, ?, ?)",
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
            "INSERT INTO provider_sessions (session_id, handoff_id, provider, status, request_digest, "
            "package_digest, budget_json, turns_used, elapsed_seconds, changed_file_count, return_id, "
            "failure_code, provider_usage_unknown, idempotency_key, created_at, updated_at, finished_at, "
            "preview_json) VALUES (?, ?, 'codex', 'ready_for_review', ?, ?, '{}', 1, 1, 1, ?, NULL, "
            "1, ?, ?, ?, ?, '{}')",
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
            "INSERT INTO provider_adoption_candidates (candidate_id, session_id, return_id, status, "
            "base_commit, change_set_digest, changed_file_count, validation_json, failure_code, "
            "idempotency_key, created_at, updated_at, finished_at, preview_json) "
            "VALUES (?, ?, ?, 'adoption_ready', ?, ?, 1, '[]', NULL, ?, ?, ?, ?, '{}')",
            (
                adoption_id,
                session_id,
                return_id,
                base_commit,
                change_set_digest,
                f"adoption-{adoption_id}",
                now.isoformat(),
                now.isoformat(),
                now.isoformat(),
            ),
        )
        connection.execute(
            "INSERT INTO approvals (approval_id, task_id, approval_type, scope_json, status, token_hash, "
            "requested_by, expires_at, requested_at, resolved_by, resolved_at, decision_reason) "
            "VALUES (?, NULL, 'provider.commit.create-v1', '{}', ?, 'hash', 'test', ?, ?, 'owner', ?, 'test')",
            (
                commit_approval_id,
                ApprovalStatus.APPROVED.value,
                (now + timedelta(hours=1)).isoformat(),
                now.isoformat(),
                now.isoformat(),
            ),
        )
        connection.execute(
            "INSERT INTO provider_commit_candidates (commit_candidate_id, adoption_candidate_id, session_id, "
            "return_id, status, base_commit, change_set_digest, tree_sha, commit_sha, local_ref, approval_id, "
            "idempotency_key, validation_json, failure_code, author_time_utc, created_at, updated_at, "
            "finished_at, preview_json) VALUES (?, ?, ?, ?, 'commit_ready', ?, ?, ?, ?, ?, ?, ?, '[]', "
            "NULL, ?, ?, ?, ?, '{}')",
            (
                commit_id,
                adoption_id,
                session_id,
                return_id,
                base_commit,
                change_set_digest,
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
        connection.execute(
            "INSERT INTO approvals (approval_id, task_id, approval_type, scope_json, status, token_hash, "
            "requested_by, expires_at, requested_at, resolved_by, resolved_at, decision_reason) "
            "VALUES (?, NULL, ?, ?, ?, 'hash', 'provider-publication', ?, ?, 'owner', ?, 'e2e')",
            (
                publication_approval_id,
                ProviderPublicationService.APPROVAL_TYPE,
                json.dumps(scope, sort_keys=True, separators=(",", ":")),
                ApprovalStatus.APPROVED.value,
                (now + timedelta(minutes=30)).isoformat(),
                now.isoformat(),
                now.isoformat(),
            ),
        )
        connection.execute(
            "INSERT INTO provider_publication_candidates (publication_candidate_id, commit_candidate_id, "
            "session_id, handoff_id, status, repo_url, repository_slug, base_ref, base_commit, commit_sha, "
            "change_set_digest, remote_ref, remote_branch, approval_id, idempotency_key, pr_title_digest, "
            "pr_body_digest, pr_number, pr_url, pr_head_sha, validation_json, failure_code, created_at, "
            "updated_at, finished_at, preview_json) VALUES (?, ?, ?, ?, ?, ?, ?, 'feature/verified-baseline', "
            "?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, '[]', NULL, ?, ?, NULL, '{}')",
            (
                publication_id,
                commit_id,
                session_id,
                handoff_id,
                ProviderPublicationStatus.WAITING_APPROVAL.value,
                repo_url,
                "jerryjwres-hue/picotoopet-v2.0",
                base_commit,
                commit_sha,
                change_set_digest,
                remote_ref,
                remote_branch,
                publication_approval_id,
                f"publication-{publication_id}",
                title_digest,
                body_digest,
                now.isoformat(),
                now.isoformat(),
            ),
        )
    return publication_id, remote_ref


def test_approved_publication_pushes_exact_sha_and_creates_verified_draft_pr(tmp_path: Path) -> None:
    repository, remote, base_commit, commit_sha = make_git_fixture(tmp_path)
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    queue = DiagnosticQueueRepository(database)
    fake_gh = make_fake_gh(tmp_path, commit_sha)
    publication_id, remote_ref = seed_publication(
        database,
        repo_url=str(remote),
        base_commit=base_commit,
        commit_sha=commit_sha,
    )
    coordinator = ProviderPublicationExecutionCoordinator(
        database=database,
        queue=queue,
        repository=repository,
        github_cli_executable=fake_gh,
    )

    coordinator.enqueue_pending()
    queued = database.fetchone(
        "SELECT * FROM tasks WHERE task_type = ?",
        (ProviderPublicationExecutionCoordinator.TASK_TYPE,),
    )
    assert queued is not None
    assert queued["status"] == TaskStatus.QUEUED.value
    assert queued["max_attempts"] == 1

    runtime = WorkerRuntime(
        queue=queue,
        state_store=WorkerStateStore(tmp_path / "worker-state.json", stale_after_seconds=30),
        worker_id="publication-e2e",
        handlers={ProviderPublicationExecutionCoordinator.TASK_TYPE: coordinator.handler},
        lease_seconds=60,
        heartbeat_seconds=5,
        poll_seconds=0.01,
    )
    result = runtime.run_once()
    assert result.processed is True
    assert result.succeeded is True

    row = database.fetchone(
        "SELECT * FROM provider_publication_candidates WHERE publication_candidate_id = ?",
        (publication_id,),
    )
    assert row is not None
    assert row["status"] == ProviderPublicationStatus.PR_READY.value
    assert row["pr_number"] == 77
    assert row["pr_head_sha"] == commit_sha
    checks = json.loads(row["validation_json"])
    assert "base_exact" in checks
    assert "remote_ref_exact" in checks
    assert "pr_exact" in checks
    remote_sha = git(repository, "ls-remote", "--refs", str(remote), remote_ref).split()[0]
    assert remote_sha == commit_sha

    # Crash-window replay must adopt exact remote/PR facts rather than create a different write.
    database.execute(
        "UPDATE provider_publication_candidates SET status = ?, pr_number = NULL, pr_url = NULL, "
        "pr_head_sha = NULL, finished_at = NULL WHERE publication_candidate_id = ?",
        (ProviderPublicationStatus.QUEUED.value, publication_id),
    )
    replay_task = queue.create(
        __import__("picotoopet_core.domain.models", fromlist=["TaskCreate"]).TaskCreate(
            task_type=ProviderPublicationExecutionCoordinator.TASK_TYPE,
            payload=coordinator._payload_from_row(row).model_dump(mode="json"),
            priority=42,
            resource_tag="provider-publication-replay",
            idempotency_key=f"publication-replay:{publication_id}",
            max_attempts=1,
            timeout_seconds=300,
        )
    )
    replay = runtime.run_once()
    assert replay.processed is True and replay.succeeded is True
    assert queue.get(replay_task.task_id).status is TaskStatus.COMPLETED
    recovered = database.fetchone(
        "SELECT status, pr_number, pr_head_sha FROM provider_publication_candidates "
        "WHERE publication_candidate_id = ?",
        (publication_id,),
    )
    assert recovered is not None
    assert recovered["status"] == ProviderPublicationStatus.PR_READY.value
    assert recovered["pr_number"] == 77
    assert recovered["pr_head_sha"] == commit_sha
    database.close()
