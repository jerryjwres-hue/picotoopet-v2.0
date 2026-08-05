from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from picotoopet_core.db.database import Database
from picotoopet_core.handoffs.approvals import HandoffApprovalService
from picotoopet_core.handoffs.models import HandoffPrepareRequest
from picotoopet_core.handoffs.service import HandoffService
from picotoopet_core.queue.repository import QueueRepository
from picotoopet_core.returns.models import ReturnEntryKind, ReturnPackageEntry, ReturnStatus
from picotoopet_core.returns.service import ReturnConflict, ReturnPolicyError, ReturnValidationService


class FixedClock:
    """为 Return ID、事件和验证时间提供可重复 UTC 时钟。"""

    def __init__(self) -> None:
        self.current = datetime(2026, 8, 5, 22, 30, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.current


def make_services(tmp_path: Path) -> tuple[Database, HandoffService, ReturnValidationService]:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    queue = QueueRepository(database)
    approvals = HandoffApprovalService(database, queue)
    clock = FixedClock()
    handoffs = HandoffService(database, approvals, clock=clock)
    returns = ReturnValidationService(database, handoffs, clock=clock)
    return database, handoffs, returns


def make_approved_handoff(database: Database, handoffs: HandoffService) -> str:
    prepared = handoffs.prepare(
        HandoffPrepareRequest(
            template_id="picotoopet-repo-maintenance-v1",
            title="验证 Return 合同",
            objective="运行本地零变更 Return 合同验证，不执行 Provider。",
            expires_seconds=1800,
        ),
        idempotency_key="prepare-return-001",
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
            json.dumps(preview, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            prepared.handoff_id,
        ),
    )
    return prepared.handoff_id


def test_approved_handoff_runs_deterministic_idempotent_return_self_test(tmp_path: Path) -> None:
    database, handoffs, returns = make_services(tmp_path)
    handoff_id = make_approved_handoff(database, handoffs)

    first = returns.run_self_test(handoff_id, idempotency_key="return-self-test-001")
    replay = returns.run_self_test(handoff_id, idempotency_key="return-self-test-001")

    assert replay == first
    assert first.status is ReturnStatus.CONTRACT_VALIDATED
    assert first.provider == "local-contract-self-test"
    assert first.changed_file_count == 0
    assert first.event_count == 3
    assert len(first.manifest_digest) == 64
    assert first.quarantine_code is None
    assert all(item.passed for item in first.validation_checks)
    assert database.scalar("SELECT COUNT(*) FROM returns") == 1
    database.close()


def test_return_self_test_requires_approved_handoff(tmp_path: Path) -> None:
    database, handoffs, returns = make_services(tmp_path)
    prepared = handoffs.prepare(
        HandoffPrepareRequest(
            template_id="picotoopet-repo-maintenance-v1",
            title="尚未批准",
            objective="未批准 Handoff 不得进入 Return 验证。",
            expires_seconds=1800,
        ),
        idempotency_key="prepare-return-unapproved",
    )

    with pytest.raises(ReturnPolicyError, match="approved"):
        returns.run_self_test(
            prepared.handoff_id,
            idempotency_key="return-self-test-unapproved",
        )
    assert database.scalar("SELECT COUNT(*) FROM returns") == 0
    database.close()


def test_reused_idempotency_key_rejects_different_handoff(tmp_path: Path) -> None:
    database, handoffs, returns = make_services(tmp_path)
    first_handoff = make_approved_handoff(database, handoffs)
    returns.run_self_test(first_handoff, idempotency_key="return-self-test-shared")

    second = handoffs.prepare(
        HandoffPrepareRequest(
            template_id="picotoopet-repo-maintenance-v1",
            title="第二个 Handoff",
            objective="不同 Handoff 不得复用同一 Return 幂等键。",
            expires_seconds=1800,
        ),
        idempotency_key="prepare-return-002",
    )
    row = database.fetchone(
        "SELECT preview_json FROM handoffs WHERE handoff_id = ?",
        (second.handoff_id,),
    )
    assert row is not None
    preview = json.loads(row["preview_json"])
    preview["status"] = "approved"
    database.execute(
        "UPDATE handoffs SET status = ?, preview_json = ? WHERE handoff_id = ?",
        (
            "approved",
            json.dumps(preview, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            second.handoff_id,
        ),
    )

    with pytest.raises(ReturnConflict, match="Idempotency-Key"):
        returns.run_self_test(
            second.handoff_id,
            idempotency_key="return-self-test-shared",
        )
    database.close()


def test_path_escape_and_symlink_packages_are_quarantined(tmp_path: Path) -> None:
    database, handoffs, returns = make_services(tmp_path)
    handoff_id = make_approved_handoff(database, handoffs)
    handoff = handoffs.get(handoff_id)

    path_escape = returns.build_self_test_entries(handoff, return_id="return-path-escape")
    path_escape["../outside.txt"] = ReturnPackageEntry(content=b"escape")
    escaped = returns.validate_entries(
        handoff,
        path_escape,
        idempotency_key="return-path-escape",
    )

    symlink = returns.build_self_test_entries(handoff, return_id="return-symlink")
    symlink["summary.md"] = ReturnPackageEntry(
        content=b"target",
        kind=ReturnEntryKind.SYMLINK,
    )
    linked = returns.validate_entries(
        handoff,
        symlink,
        idempotency_key="return-symlink",
    )

    assert escaped.status is ReturnStatus.QUARANTINED
    assert escaped.quarantine_code == "PATH_POLICY_DENIED"
    assert linked.status is ReturnStatus.QUARANTINED
    assert linked.quarantine_code == "LINK_ENTRY_DENIED"
    assert "outside.txt" not in escaped.model_dump_json()
    assert "target" not in linked.model_dump_json()
    database.close()
