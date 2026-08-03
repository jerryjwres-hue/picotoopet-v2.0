"""诊断采集器固定白名单与隐私回归。"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from picotoopet_core.diagnostics.collector import collect_snapshot
from picotoopet_core.diagnostics.models import (
    DiagnosticFacts,
    DiagnosticSnapshotRequest,
)


def _facts() -> DiagnosticFacts:
    return DiagnosticFacts(
        core_version="2.3.0",
        core_health_state="online",
        database_schema_version=1,
        worker_id="picotoopet-m4-test",
        worker_state="online",
        worker_reason="idle",
        worker_supported_task_types=(
            "system.noop",
            "system.diagnostic_snapshot",
        ),
        worker_last_heartbeat_at=datetime.now(UTC),
        queue_counts={"Queued": 2, "Running": 1, "Completed": 5},
        oldest_queued_age_seconds=4,
    )


def test_collector_outputs_only_fixed_non_sensitive_cards() -> None:
    result = collect_snapshot(DiagnosticSnapshotRequest(), _facts())
    document = result.model_dump(mode="json")
    serialized = json.dumps(document, ensure_ascii=False, sort_keys=True)

    assert set(document) == {
        "schema_version",
        "generated_at",
        "core",
        "worker",
        "queue",
        "checks",
        "warnings",
    }
    assert "/Users/" not in serialized
    assert "Authorization" not in serialized
    assert "payload_json" not in serialized
    assert "192.0.2." not in serialized
    assert [check["name"] for check in document["checks"]] == [
        "core_health",
        "worker_heartbeat",
        "queue_backlog",
    ]


def test_facts_reject_sensitive_or_unknown_inputs_before_collection() -> None:
    payload = _facts().model_dump(mode="json")
    payload.update(
        {
            "token": "secret",
            "home_path": "/Users/example",
            "ip_address": "192.0.2.10",
            "task_payloads": [{"prompt": "private"}],
        }
    )

    with pytest.raises(ValidationError):
        DiagnosticFacts.model_validate(payload)


def test_collector_honors_requested_sections_without_dynamic_fields() -> None:
    result = collect_snapshot(
        DiagnosticSnapshotRequest(sections=("worker",)),
        _facts(),
    )

    assert result.core is None
    assert result.worker is not None
    assert result.queue is None
    assert [check.name for check in result.checks] == ["worker_heartbeat"]


def test_collector_emits_stable_warning_reason_codes() -> None:
    facts = _facts().model_copy(
        update={
            "core_health_state": "degraded",
            "worker_state": "offline",
            "worker_reason": "heartbeat_stale",
            "queue_counts": {"Queued": 150},
            "oldest_queued_age_seconds": 600,
        }
    )

    result = collect_snapshot(DiagnosticSnapshotRequest(), facts)

    assert {check.reason_code for check in result.checks} == {
        "CORE_DEGRADED",
        "WORKER_OFFLINE",
        "QUEUE_BACKLOG",
    }
    assert set(result.warnings) == {
        "CORE_DEGRADED",
        "WORKER_OFFLINE",
        "QUEUE_BACKLOG",
        "QUEUE_OLD",
    }
