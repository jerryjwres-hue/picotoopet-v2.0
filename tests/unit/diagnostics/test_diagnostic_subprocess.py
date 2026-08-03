"""诊断子进程成功、异常、超时、取消和清理回归。"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from picotoopet_core.diagnostics.models import (
    DiagnosticFacts,
    DiagnosticSnapshotRequest,
    DiagnosticSnapshotResult,
)
from picotoopet_core.diagnostics.subprocess_runner import (
    DiagnosticCancelledError,
    DiagnosticCollectionError,
    DiagnosticSubprocessRunner,
    DiagnosticTimeoutError,
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
        queue_counts={"Queued": 1},
        oldest_queued_age_seconds=1,
    )


def test_subprocess_returns_validated_candidate_json(tmp_path: Path) -> None:
    runner = DiagnosticSubprocessRunner(poll_seconds=0.02, terminate_grace_seconds=0.5)

    output_path = runner.run(
        DiagnosticSnapshotRequest(),
        _facts(),
        output_dir=tmp_path,
        timeout_seconds=3,
        cancel_requested=lambda: False,
    )

    result = DiagnosticSnapshotResult.model_validate_json(output_path.read_bytes())
    assert result.schema_version == "1.0"
    assert runner.last_pid is not None


def test_subprocess_maps_child_failure_to_redacted_error(tmp_path: Path) -> None:
    runner = DiagnosticSubprocessRunner(poll_seconds=0.02, terminate_grace_seconds=0.5)

    with pytest.raises(DiagnosticCollectionError, match="诊断采集子进程失败"):
        runner.run(
            DiagnosticSnapshotRequest(),
            _facts(),
            output_dir=tmp_path,
            timeout_seconds=3,
            cancel_requested=lambda: False,
            test_fail=True,
        )


def test_subprocess_timeout_is_bounded_and_child_is_gone(tmp_path: Path) -> None:
    runner = DiagnosticSubprocessRunner(poll_seconds=0.02, terminate_grace_seconds=0.5)
    started = time.monotonic()

    with pytest.raises(DiagnosticTimeoutError):
        runner.run(
            DiagnosticSnapshotRequest(),
            _facts(),
            output_dir=tmp_path,
            timeout_seconds=0.2,
            cancel_requested=lambda: False,
            test_delay_seconds=5,
        )

    assert time.monotonic() - started < 3
    assert runner.last_pid is not None
    if os.name == "posix":
        with pytest.raises(ProcessLookupError):
            os.kill(runner.last_pid, 0)


def test_subprocess_cancellation_is_bounded_and_writes_no_result(tmp_path: Path) -> None:
    runner = DiagnosticSubprocessRunner(poll_seconds=0.02, terminate_grace_seconds=0.5)
    started = time.monotonic()

    with pytest.raises(DiagnosticCancelledError):
        runner.run(
            DiagnosticSnapshotRequest(),
            _facts(),
            output_dir=tmp_path,
            timeout_seconds=5,
            cancel_requested=lambda: time.monotonic() - started >= 0.15,
            test_delay_seconds=5,
        )

    assert time.monotonic() - started < 3
    assert not (tmp_path / "diagnostic-result.json").exists()
