"""Slice D 诊断请求和结果合同回归。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from picotoopet_core.diagnostics.models import (
    DiagnosticCheck,
    DiagnosticSnapshotRequest,
    DiagnosticSnapshotResult,
)


def _minimal_result() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "core": {
            "version": "2.3.0",
            "health_state": "online",
            "database_schema_version": 1,
        },
        "worker": {
            "worker_id": "picotoopet-m4-test",
            "state": "online",
            "reason": "idle",
            "supported_task_types": [
                "system.diagnostic_snapshot",
                "system.noop",
            ],
            "last_heartbeat_at": datetime.now(UTC).isoformat(),
        },
        "queue": {
            "counts": {"Queued": 1, "Running": 0, "Completed": 2},
            "oldest_queued_age_seconds": 3,
        },
        "checks": [
            {
                "name": "core_health",
                "status": "pass",
                "reason_code": "CORE_HEALTHY",
            }
        ],
        "warnings": [],
    }


def test_request_accepts_only_fixed_unique_sections() -> None:
    request = DiagnosticSnapshotRequest.model_validate(
        {
            "schema_version": "1.0",
            "sections": ["queue", "core", "worker"],
        }
    )

    assert request.sections == ("core", "worker", "queue")


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": "2.0", "sections": ["core"]},
        {"schema_version": "1.0", "sections": []},
        {"schema_version": "1.0", "sections": ["core", "core"]},
        {"schema_version": "1.0", "sections": ["logs"]},
        {"schema_version": "1.0", "sections": ["core"], "extra": True},
    ],
)
def test_request_rejects_unknown_duplicate_empty_or_extra_values(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        DiagnosticSnapshotRequest.model_validate(payload)


def test_result_accepts_only_fixed_cards_and_reason_codes() -> None:
    result = DiagnosticSnapshotResult.model_validate(_minimal_result())

    assert result.schema_version == "1.0"
    assert result.checks == (
        DiagnosticCheck(
            name="core_health",
            status="pass",
            reason_code="CORE_HEALTHY",
        ),
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("token", "secret"),
        ("home_path", "/Users/example"),
        ("ip_address", "192.0.2.10"),
        ("logs", ["raw log body"]),
    ],
)
def test_result_rejects_sensitive_or_unknown_top_level_fields(
    field: str,
    value: object,
) -> None:
    payload = _minimal_result()
    payload[field] = value

    with pytest.raises(ValidationError):
        DiagnosticSnapshotResult.model_validate(payload)


def test_result_rejects_unknown_check_reason_code() -> None:
    payload = _minimal_result()
    payload["checks"] = [
        {
            "name": "core_health",
            "status": "pass",
            "reason_code": "RAW_EXCEPTION_TEXT",
        }
    ]

    with pytest.raises(ValidationError):
        DiagnosticSnapshotResult.model_validate(payload)
