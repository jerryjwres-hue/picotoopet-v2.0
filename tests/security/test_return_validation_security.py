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
from picotoopet_core.returns.models import ReturnPackageEntry, ReturnStatus
from picotoopet_core.returns.service import ReturnValidationService


def make_approved(tmp_path: Path) -> tuple[Database, HandoffService, ReturnValidationService, str]:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    queue = QueueRepository(database)
    approvals = HandoffApprovalService(database, queue)
    clock = lambda: datetime(2026, 8, 5, 22, 45, tzinfo=UTC)
    handoffs = HandoffService(database, approvals, clock=clock)
    returns = ReturnValidationService(database, handoffs, clock=clock)
    prepared = handoffs.prepare(
        HandoffPrepareRequest(
            template_id="picotoopet-repo-maintenance-v1",
            title="Return 安全攻击夹具",
            objective="验证所有越界 Return 都进入隔离。",
            expires_seconds=1800,
        ),
        idempotency_key="prepare-return-security",
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
    return database, handoffs, returns, prepared.handoff_id


def rewrite_json(
    entries: dict[str, ReturnPackageEntry],
    path: str,
    mutate,
) -> None:
    payload = json.loads(entries[path].content.decode("utf-8"))
    mutate(payload)
    entries[path] = ReturnPackageEntry(
        content=(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
    )


@pytest.mark.parametrize(
    ("name", "mutate", "expected_code"),
    [
        (
            "digest-mismatch",
            lambda entries: rewrite_json(
                entries,
                "return_manifest.json",
                lambda payload: payload.__setitem__("request_digest", "f" * 64),
            ),
            "HANDOFF_BINDING_MISMATCH",
        ),
        (
            "changed-file",
            lambda entries: rewrite_json(
                entries,
                "changed_files.json",
                lambda payload: payload["files"].append(
                    {
                        "path": "src/evil.py",
                        "operation": "added",
                        "binary": False,
                    }
                ),
            ),
            "CHANGED_FILES_DENIED",
        ),
        (
            "provider-test-pass",
            lambda entries: rewrite_json(
                entries,
                "test_report.json",
                lambda payload: payload["tests"][0].__setitem__("status", "pass"),
            ),
            "PROVIDER_CLAIM_DENIED",
        ),
        (
            "secret-event",
            lambda entries: entries.__setitem__(
                "session_events.ndjson",
                ReturnPackageEntry(
                    content=(
                        entries["session_events.ndjson"].content
                        + b'{"event_id":"secret","sequence":4,"event_type":"provider.warning",'
                        + b'"payload":{"message":"Authorization: Bearer abcdef"}}\n'
                    )
                ),
            ),
            "SECRET_CONTENT_DENIED",
        ),
        (
            "undeclared-executable",
            lambda entries: entries.__setitem__(
                "artifacts/evil.exe",
                ReturnPackageEntry(content=b"MZ"),
            ),
            "FILE_ALLOWLIST_DENIED",
        ),
    ],
)
def test_untrusted_return_mutations_are_quarantined_without_raw_content(
    tmp_path: Path,
    name: str,
    mutate,
    expected_code: str,
) -> None:
    database, handoffs, returns, handoff_id = make_approved(tmp_path)
    handoff = handoffs.get(handoff_id)
    return_id = f"return-{name}"
    entries = returns.build_self_test_entries(handoff, return_id=return_id)
    mutate(entries)
    returns.resign_entries(entries)

    record = returns.validate_entries(
        handoff,
        entries,
        idempotency_key=return_id,
        return_id=return_id,
    )

    assert record.status is ReturnStatus.QUARANTINED
    assert record.quarantine_code == expected_code
    serialized = record.model_dump_json().lower()
    assert "authorization" not in serialized
    assert "bearer" not in serialized
    assert "evil.exe" not in serialized
    assert "src/evil.py" not in serialized
    database.close()


def test_event_sequence_gap_and_duplicate_event_id_are_quarantined(tmp_path: Path) -> None:
    database, handoffs, returns, handoff_id = make_approved(tmp_path)
    handoff = handoffs.get(handoff_id)

    gap_entries = returns.build_self_test_entries(handoff, return_id="return-gap")
    events = [
        json.loads(line)
        for line in gap_entries["session_events.ndjson"].content.decode("utf-8").splitlines()
    ]
    events[2]["sequence"] = 4
    gap_entries["session_events.ndjson"] = ReturnPackageEntry(
        content=("\n".join(json.dumps(item, sort_keys=True) for item in events) + "\n").encode()
    )
    returns.resign_entries(gap_entries)

    duplicate_entries = returns.build_self_test_entries(handoff, return_id="return-duplicate")
    events = [
        json.loads(line)
        for line in duplicate_entries["session_events.ndjson"].content.decode("utf-8").splitlines()
    ]
    events[2]["event_id"] = events[1]["event_id"]
    duplicate_entries["session_events.ndjson"] = ReturnPackageEntry(
        content=("\n".join(json.dumps(item, sort_keys=True) for item in events) + "\n").encode()
    )
    returns.resign_entries(duplicate_entries)

    gap = returns.validate_entries(
        handoff,
        gap_entries,
        idempotency_key="return-gap",
        return_id="return-gap",
    )
    duplicate = returns.validate_entries(
        handoff,
        duplicate_entries,
        idempotency_key="return-duplicate",
        return_id="return-duplicate",
    )

    assert gap.status is ReturnStatus.QUARANTINED
    assert gap.quarantine_code == "EVENT_SEQUENCE_INVALID"
    assert duplicate.status is ReturnStatus.QUARANTINED
    assert duplicate.quarantine_code == "EVENT_ID_DUPLICATE"
    database.close()
