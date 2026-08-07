from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from picotoopet_core.db.database import Database
from picotoopet_core.handoffs.approvals import HandoffApprovalService
from picotoopet_core.handoffs.models import HandoffPrepareRequest
from picotoopet_core.handoffs.service import HandoffService
from picotoopet_core.providers.models import ProviderSessionStatus, ProviderUsageStatus
from picotoopet_core.providers.service import (
    ProviderSessionConflict,
    ProviderSessionPolicyError,
    ProviderSessionService,
)
from picotoopet_core.queue.repository import QueueRepository


class MutableClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 8, 7, 3, 30, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, delta: timedelta) -> None:
        self.current += delta


def make_services(
    tmp_path: Path,
) -> tuple[Database, HandoffService, ProviderSessionService, MutableClock]:
    clock = MutableClock()
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    queue = QueueRepository(database)
    approvals = HandoffApprovalService(database, queue)
    handoffs = HandoffService(database, approvals, clock=clock)
    providers = ProviderSessionService(database, handoffs, clock=clock)
    return database, handoffs, providers, clock


def prepare_approved_codex_handoff(
    database: Database,
    handoffs: HandoffService,
    *,
    key: str,
) -> str:
    prepared = handoffs.prepare(
        HandoffPrepareRequest(
            template_id="picotoopet-repo-maintenance-codex-v1",
            title="受控 Codex 维护任务",
            objective="仅在批准范围内修改最多五个文件并返回安全摘要。",
            expires_seconds=1800,
        ),
        idempotency_key=key,
    )
    row = database.fetchone(
        "SELECT preview_json FROM handoffs WHERE handoff_id = ?",
        (prepared.handoff_id,),
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
            prepared.handoff_id,
        ),
    )
    return prepared.handoff_id


def test_codex_template_binds_provider_commit_tests_and_budget(tmp_path: Path) -> None:
    database, handoffs, _, _ = make_services(tmp_path)

    templates = {template.template_id: template for template in handoffs.templates()}
    assert set(templates) == {
        "picotoopet-repo-maintenance-v1",
        "picotoopet-repo-maintenance-codex-v1",
    }
    assert templates["picotoopet-repo-maintenance-codex-v1"].provider == "codex"
    assert (
        templates["picotoopet-repo-maintenance-codex-v1"].base_commit
        == "65d5ba0ef5a4ac6f6b3ca61b0f852599d1286d6f"
    )

    codex = handoffs.prepare(
        HandoffPrepareRequest(
            template_id="picotoopet-repo-maintenance-codex-v1",
            title="Codex 任务",
            objective="执行一次低预算维护。",
            expires_seconds=1800,
        ),
        idempotency_key="codex-template",
    )
    manual = handoffs.prepare(
        HandoffPrepareRequest(
            template_id="picotoopet-repo-maintenance-v1",
            title="Codex 任务",
            objective="执行一次低预算维护。",
            expires_seconds=1800,
        ),
        idempotency_key="manual-template",
    )

    assert codex.provider == "codex"
    assert codex.request_digest != manual.request_digest
    assert codex.package_digest != manual.package_digest
    assert codex.budget_summary == (
        "8 turns · 900 秒 · 1 并发 · 5 文件 · 0 自动重试 · 无网络工具"
    )
    assert "mac-worker-arm64" in codex.required_tests
    database.close()


def test_confirmed_usage_creates_one_idempotent_session_per_handoff(
    tmp_path: Path,
) -> None:
    database, handoffs, providers, _ = make_services(tmp_path)
    handoff_id = prepare_approved_codex_handoff(
        database,
        handoffs,
        key="prepare-codex-approved",
    )

    confirmation = providers.confirm_usage(
        handoff_id,
        ProviderUsageStatus.CONFIRMED_AVAILABLE,
        idempotency_key="usage-confirmation-001",
    )
    replay = providers.confirm_usage(
        handoff_id,
        ProviderUsageStatus.CONFIRMED_AVAILABLE,
        idempotency_key="usage-confirmation-001",
    )
    assert replay == confirmation
    assert confirmation.expires_at - confirmation.confirmed_at == timedelta(minutes=15)
    assert confirmation.budget.max_turns == 8
    assert confirmation.budget.timeout_seconds == 900
    assert confirmation.budget.automatic_retries == 0

    session = providers.create_codex_session(
        handoff_id,
        idempotency_key="provider-session-001",
    )
    session_replay = providers.create_codex_session(
        handoff_id,
        idempotency_key="provider-session-001",
    )
    assert session_replay == session
    assert session.status is ProviderSessionStatus.WAITING_PROVIDER_READY
    assert database.scalar("SELECT COUNT(*) FROM provider_sessions") == 1

    with pytest.raises(ProviderSessionConflict, match="只能启动一次"):
        providers.create_codex_session(
            handoff_id,
            idempotency_key="provider-session-002",
        )
    database.close()


def test_low_exhausted_unknown_or_expired_usage_cannot_start(tmp_path: Path) -> None:
    for index, status in enumerate(
        (
            ProviderUsageStatus.CONFIRMED_LOW,
            ProviderUsageStatus.CONFIRMED_EXHAUSTED,
            ProviderUsageStatus.UNKNOWN,
        )
    ):
        case = tmp_path / str(index)
        case.mkdir()
        database, handoffs, providers, _ = make_services(case)
        handoff_id = prepare_approved_codex_handoff(
            database,
            handoffs,
            key=f"prepare-{index}",
        )
        providers.confirm_usage(
            handoff_id,
            status,
            idempotency_key=f"confirm-{index}",
        )
        with pytest.raises(ProviderSessionPolicyError, match="confirmed_available"):
            providers.create_codex_session(
                handoff_id,
                idempotency_key=f"session-{index}",
            )
        database.close()

    expired_case = tmp_path / "expired"
    expired_case.mkdir()
    database, handoffs, providers, clock = make_services(expired_case)
    handoff_id = prepare_approved_codex_handoff(
        database,
        handoffs,
        key="prepare-expired",
    )
    providers.confirm_usage(
        handoff_id,
        ProviderUsageStatus.CONFIRMED_AVAILABLE,
        idempotency_key="confirm-expired",
    )
    clock.advance(timedelta(minutes=16))
    with pytest.raises(ProviderSessionPolicyError, match="额度人工确认已过期"):
        providers.create_codex_session(
            handoff_id,
            idempotency_key="session-expired",
        )
    database.close()
