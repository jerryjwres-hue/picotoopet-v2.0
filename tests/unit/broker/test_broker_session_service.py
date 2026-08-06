from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from picotoopet_core.broker.models import BrokerSessionStatus
from picotoopet_core.broker.service import (
    BrokerSessionConflict,
    BrokerSessionPolicyError,
    BrokerSessionService,
)
from picotoopet_core.db.database import Database
from picotoopet_core.handoffs.approvals import HandoffApprovalService
from picotoopet_core.handoffs.models import HandoffPrepareRequest
from picotoopet_core.handoffs.service import HandoffService
from picotoopet_core.queue.repository import QueueRepository
from picotoopet_core.returns.service import ReturnValidationService


class FixedClock:
    """为 Broker Session 提供稳定 UTC 时间。"""

    def __init__(self) -> None:
        self.current = datetime(2026, 8, 6, 0, 20, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.current


def make_services(
    tmp_path: Path,
) -> tuple[Database, HandoffService, BrokerSessionService]:
    database  = Database(tmp_path / "core.db")
    clock     = FixedClock()
    database.open()
    database.apply_migrations()
    queue     = QueueRepository(database)
    approvals = HandoffApprovalService(database, queue)
    handoffs  = HandoffService(database, approvals, clock=clock)
    returns   = ReturnValidationService(database, handoffs, clock=clock)
    broker    = BrokerSessionService(
        database,
        handoffs,
        returns,
        api_token="a" * 32,
        clock=clock,
    )
    return database, handoffs, broker


def prepare_handoff(
    database: Database,
    handoffs: HandoffService,
    *,
    prepare_key: str,
    approved: bool,
) -> str:
    prepared = handoffs.prepare(
        HandoffPrepareRequest(
            template_id="picotoopet-repo-maintenance-v1",
            title="验证 Mock Dev Broker",
            objective="运行固定沙盒和 Return 导回验证，不调用真实 Provider。",
            expires_seconds=1800,
        ),
        idempotency_key=prepare_key,
    )
    if approved:
        row = database.fetchone(
            "SELECT preview_json FROM handoffs WHERE handoff_id = ?",
            (prepared.handoff_id,),
        )
        assert row is not None
        preview           = json.loads(row["preview_json"])
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


def test_approved_handoff_reserves_idempotent_mock_broker_session(
    tmp_path: Path,
) -> None:
    database, handoffs, broker = make_services(tmp_path)
    handoff_id = prepare_handoff(
        database,
        handoffs,
        prepare_key="prepare-broker-approved",
        approved=True,
    )

    first = broker.reserve_mock_session(
        handoff_id,
        idempotency_key="broker-session-create-001",
    )
    replay = broker.reserve_mock_session(
        handoff_id,
        idempotency_key="broker-session-create-001",
    )

    assert replay == first
    assert first.record.status is BrokerSessionStatus.RESERVED
    assert first.record.provider == "local-mock-dev-broker"
    assert first.record.timeout_seconds == 30
    assert len(first.capability) == 64
    assert first.capability not in first.record.model_dump_json()
    assert database.scalar("SELECT COUNT(*) FROM broker_sessions") == 1
    row = database.fetchone(
        "SELECT * FROM broker_sessions WHERE session_id = ?",
        (first.record.session_id,),
    )
    assert row is not None
    assert first.capability not in json.dumps(dict(row), default=str)
    database.close()


def test_mock_broker_session_requires_approved_handoff(tmp_path: Path) -> None:
    database, handoffs, broker = make_services(tmp_path)
    handoff_id = prepare_handoff(
        database,
        handoffs,
        prepare_key="prepare-broker-unapproved",
        approved=False,
    )

    with pytest.raises(BrokerSessionPolicyError, match="approved"):
        broker.reserve_mock_session(
            handoff_id,
            idempotency_key="broker-session-unapproved",
        )

    assert database.scalar("SELECT COUNT(*) FROM broker_sessions") == 0
    database.close()


def test_broker_idempotency_key_cannot_bind_two_handoffs(tmp_path: Path) -> None:
    database, handoffs, broker = make_services(tmp_path)
    first_handoff = prepare_handoff(
        database,
        handoffs,
        prepare_key="prepare-broker-first",
        approved=True,
    )
    second_handoff = prepare_handoff(
        database,
        handoffs,
        prepare_key="prepare-broker-second",
        approved=True,
    )
    broker.reserve_mock_session(
        first_handoff,
        idempotency_key="broker-session-shared",
    )

    with pytest.raises(BrokerSessionConflict, match="Idempotency-Key"):
        broker.reserve_mock_session(
            second_handoff,
            idempotency_key="broker-session-shared",
        )
    database.close()
