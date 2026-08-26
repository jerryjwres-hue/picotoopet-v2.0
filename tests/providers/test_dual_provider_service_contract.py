from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from picotoopet_core.db.database import Database
from picotoopet_core.handoffs.approvals import HandoffApprovalService
from picotoopet_core.handoffs.models import HandoffPrepareRequest
from picotoopet_core.handoffs.service import HandoffService
from picotoopet_core.providers.models import (
    ProviderReadinessStatus,
    ProviderSessionStatus,
    ProviderUsageStatus,
)
from picotoopet_core.providers.service import ProviderSessionService
from picotoopet_core.queue.repository import QueueRepository


class FixedClock:
    def __call__(self) -> datetime:
        return datetime(2026, 8, 19, 2, 30, tzinfo=UTC)


def _services(tmp_path: Path) -> tuple[Database, HandoffService, ProviderSessionService]:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    queue = QueueRepository(database)
    approvals = HandoffApprovalService(database, queue)
    clock = FixedClock()
    handoffs = HandoffService(database, approvals, clock=clock)
    providers = ProviderSessionService(
        database,
        handoffs,
        clock=clock,
        readiness_by_provider=lambda provider: ProviderReadinessStatus.READY,
    )
    return database, handoffs, providers


def _approve(database: Database, handoff_id: str) -> None:
    row = database.fetchone(
        "SELECT preview_json FROM handoffs WHERE handoff_id = ?",
        (handoff_id,),
    )
    assert row is not None
    preview = json.loads(row["preview_json"])
    preview["status"] = "approved"
    database.execute(
        "UPDATE handoffs SET status = ?, preview_json = ? WHERE handoff_id = ?",
        (
            "approved",
            json.dumps(
                preview,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            handoff_id,
        ),
    )


def test_handoff_service_exposes_fixed_claude_code_template(tmp_path: Path) -> None:
    database, handoffs, _ = _services(tmp_path)
    templates = {item.template_id: item for item in handoffs.templates()}

    assert set(templates) == {
        "picotoopet-repo-maintenance-v1",
        "picotoopet-repo-maintenance-codex-v1",
        "picotoopet-repo-maintenance-claude-code-v1",
    }
    assert templates["picotoopet-repo-maintenance-claude-code-v1"].provider == "claude_code"

    prepared = handoffs.prepare(
        HandoffPrepareRequest(
            template_id="picotoopet-repo-maintenance-claude-code-v1",
            title="Claude Code bounded maintenance",
            objective="Modify only the approved isolated worktree and return a bounded result.",
            expires_seconds=1800,
        ),
        idempotency_key="prepare-claude-code",
    )

    assert prepared.provider == "claude_code"
    assert prepared.budget_summary == (
        "8 turns · 900 秒 · 1 并发 · 5 文件 · 0 自动重试 · 无网络工具"
    )
    assert "mac-worker-arm64" in prepared.required_tests
    database.close()


def test_provider_status_is_provider_specific_without_exposing_credentials(tmp_path: Path) -> None:
    database, _, providers = _services(tmp_path)

    codex = providers.provider_status("codex")
    claude = providers.provider_status("claude_code")

    assert codex.provider == "codex"
    assert claude.provider == "claude_code"
    assert codex.readiness is ProviderReadinessStatus.READY
    assert claude.readiness is ProviderReadinessStatus.READY
    database.close()


def test_claude_code_usage_and_session_infer_provider_from_handoff(tmp_path: Path) -> None:
    database, handoffs, providers = _services(tmp_path)
    prepared = handoffs.prepare(
        HandoffPrepareRequest(
            template_id="picotoopet-repo-maintenance-claude-code-v1",
            title="Claude Code bounded maintenance",
            objective="Modify only the approved isolated worktree and return a bounded result.",
            expires_seconds=1800,
        ),
        idempotency_key="prepare-claude-session",
    )
    _approve(database, prepared.handoff_id)

    confirmation = providers.confirm_usage(
        prepared.handoff_id,
        ProviderUsageStatus.CONFIRMED_AVAILABLE,
        idempotency_key="confirm-claude-session",
    )
    session = providers.create_claude_code_session(
        prepared.handoff_id,
        idempotency_key="create-claude-session",
    )

    assert confirmation.provider == "claude_code"
    assert session.provider == "claude_code"
    assert session.status is ProviderSessionStatus.WAITING_PROVIDER_READY
    assert database.scalar(
        "SELECT provider FROM provider_sessions WHERE session_id = ?",
        (session.session_id,),
    ) == "claude_code"
    database.close()
