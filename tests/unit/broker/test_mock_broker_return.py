from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from picotoopet_core.broker.models import (
    BrokerReturnFile,
    BrokerReturnFileName,
    BrokerSessionCreateResult,
    MockBrokerReturnEnvelope,
)
from picotoopet_core.broker.service import BrokerSessionPolicyError, BrokerSessionService
from picotoopet_core.db.database import Database
from picotoopet_core.handoffs.approvals import HandoffApprovalService
from picotoopet_core.handoffs.models import HandoffPrepareRequest, HandoffRecord
from picotoopet_core.handoffs.service import HandoffService
from picotoopet_core.queue.repository import QueueRepository
from picotoopet_core.returns.models import ReturnPackageEntry
from picotoopet_core.returns.service import ReturnValidationService


class FixedClock:
    """为 Broker Return 固定 UTC 时间。"""

    def __call__(self) -> datetime:
        return datetime(2026, 8, 6, 0, 30, tzinfo=UTC)


def make_services(
    tmp_path: Path,
) -> tuple[Database, HandoffService, ReturnValidationService, BrokerSessionService]:
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
    return database, handoffs, returns, broker


def make_approved_handoff(
    database: Database,
    handoffs: HandoffService,
) -> HandoffRecord:
    prepared = handoffs.prepare(
        HandoffPrepareRequest(
            template_id="picotoopet-repo-maintenance-v1",
            title="Mock Broker Return",
            objective="验证固定沙盒 Return，不调用真实 Provider。",
            expires_seconds=1800,
        ),
        idempotency_key="prepare-mock-broker-return",
    )
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
            canonical_json(preview),
            prepared.handoff_id,
        ),
    )
    return handoffs.get(prepared.handoff_id)


def make_envelope(
    returns: ReturnValidationService,
    session: BrokerSessionCreateResult,
    handoff: HandoffRecord,
) -> MockBrokerReturnEnvelope:
    return_id = str(uuid4())
    proof = (
        "Mock Provider proof\n"
        f"session={session.record.session_id}\n"
        f"package={handoff.package_digest}\n"
    ).encode("utf-8")
    event_types = (
        "broker.started",
        "broker.sandbox.ready",
        "provider.returned",
        "broker.return.submitted",
    )
    events = [
        {
            "event_id": f"{return_id}-{sequence:03d}",
            "sequence": sequence,
            "session_id": session.record.session_id,
            "handoff_id": handoff.handoff_id,
            "return_id": return_id,
            "provider": "local-mock-dev-broker",
            "event_type": event_type,
            "payload_version": "1.0.0",
            "payload": {"summary": f"固定 Mock Broker 事件 {sequence}。"},
        }
        for sequence, event_type in enumerate(event_types, 1)
    ]
    entries: dict[str, ReturnPackageEntry] = {
        "session_events.ndjson": ReturnPackageEntry(
            ("\n".join(canonical_json(item) for item in events) + "\n").encode(
                "utf-8"
            )
        ),
        "summary.md": ReturnPackageEntry(b"# Mock Broker Return\n"),
        "changed_files.json": ReturnPackageEntry(
            json_bytes(
                {
                    "schema_version": "1.0.0",
                    "files": [
                        {
                            "path": "docs/mock-provider-proof.txt",
                            "change_type": "added",
                            "sha256": returns._sha256(proof),
                        }
                    ],
                }
            )
        ),
        "test_report.json": ReturnPackageEntry(
            json_bytes(
                {
                    "schema_version": "1.0.0",
                    "tests": [
                        {
                            "command_id": "project-tests",
                            "status": "not_run",
                        }
                    ],
                }
            )
        ),
        "build_report.json": ReturnPackageEntry(
            json_bytes({"schema_version": "1.0.0", "status": "not_run"})
        ),
        "security_report.json": ReturnPackageEntry(
            json_bytes(
                {
                    "schema_version": "1.0.0",
                    "checks": ["sandbox", "secret_scan"],
                }
            )
        ),
        "questions.md": ReturnPackageEntry(b"# Questions\n\nNone.\n"),
        "changes/docs/mock-provider-proof.txt": ReturnPackageEntry(proof),
    }
    sandbox_digest  = "d" * 64
    manifest_digest = returns._content_manifest_digest(entries)
    entries["return_manifest.json"] = ReturnPackageEntry(
        json_bytes(
            {
                "schema_version": "1.0.0",
                "session_id": session.record.session_id,
                "return_id": return_id,
                "handoff_id": handoff.handoff_id,
                "request_digest": handoff.request_digest,
                "package_digest": handoff.package_digest,
                "provider": "local-mock-dev-broker",
                "base_commit": handoff.base_commit,
                "sandbox_digest": sandbox_digest,
                "changed_file_count": 1,
                "manifest_digest": manifest_digest,
            }
        )
    )
    returns.resign_entries(entries)
    files = [
        BrokerReturnFile(
            name=BrokerReturnFileName(path),
            content=entry.content.decode("utf-8"),
        )
        for path, entry in sorted(entries.items())
    ]
    return MockBrokerReturnEnvelope(
        schema_version="1.0.0",
        session_id=session.record.session_id,
        handoff_id=handoff.handoff_id,
        return_id=return_id,
        provider="local-mock-dev-broker",
        request_digest=handoff.request_digest,
        package_digest=handoff.package_digest,
        sandbox_digest=sandbox_digest,
        files=files,
    )


def test_valid_mock_broker_return_completes_session_idempotently(
    tmp_path: Path,
) -> None:
    database, handoffs, returns, broker = make_services(tmp_path)
    handoff = make_approved_handoff(database, handoffs)
    session = broker.reserve_mock_session(
        handoff.handoff_id,
        idempotency_key="mock-session-valid",
    )
    envelope = make_envelope(returns, session, handoff)

    completed = broker.ingest_mock_return(
        session.record.session_id,
        envelope,
        capability=session.capability,
        idempotency_key="mock-return-valid",
    )
    replay = broker.ingest_mock_return(
        session.record.session_id,
        envelope,
        capability=session.capability,
        idempotency_key="mock-return-valid",
    )
    record = returns.get(envelope.return_id)

    assert replay == completed
    assert completed.status.value == "completed"
    assert completed.return_id == envelope.return_id
    assert completed.event_count == 4
    assert record.status.value == "contract_validated"
    assert record.provider == "local-mock-dev-broker"
    assert record.changed_file_count == 1
    assert record.event_count == 4
    assert database.scalar("SELECT COUNT(*) FROM returns") == 1
    database.close()


def test_wrong_capability_rejects_return_without_changing_session(
    tmp_path: Path,
) -> None:
    database, handoffs, returns, broker = make_services(tmp_path)
    handoff = make_approved_handoff(database, handoffs)
    session = broker.reserve_mock_session(
        handoff.handoff_id,
        idempotency_key="mock-session-capability",
    )
    envelope = make_envelope(returns, session, handoff)

    with pytest.raises(BrokerSessionPolicyError, match="capability"):
        broker.ingest_mock_return(
            session.record.session_id,
            envelope,
            capability="0" * 64,
            idempotency_key="mock-return-capability",
        )

    assert broker.get_session(session.record.session_id).status.value == "reserved"
    assert database.scalar("SELECT COUNT(*) FROM returns") == 0
    database.close()


def test_secret_content_quarantines_mock_return(tmp_path: Path) -> None:
    database, handoffs, returns, broker = make_services(tmp_path)
    handoff = make_approved_handoff(database, handoffs)
    session = broker.reserve_mock_session(
        handoff.handoff_id,
        idempotency_key="mock-session-secret",
    )
    envelope = make_envelope(returns, session, handoff)
    files = [
        item.model_copy(update={"content": "Authorization: Bearer hidden"})
        if item.name is BrokerReturnFileName.SUMMARY
        else item
        for item in envelope.files
    ]
    unsafe = envelope.model_copy(update={"files": files})

    quarantined = broker.ingest_mock_return(
        session.record.session_id,
        unsafe,
        capability=session.capability,
        idempotency_key="mock-return-secret",
    )
    record = returns.get(envelope.return_id)

    assert quarantined.status.value == "quarantined"
    assert quarantined.failure_code == "BROKER_RETURN_QUARANTINED"
    assert record.status.value == "quarantined"
    assert record.quarantine_code == "SECRET_CONTENT_DENIED"
    assert "hidden" not in record.model_dump_json()
    database.close()


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def json_bytes(value: object) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")
