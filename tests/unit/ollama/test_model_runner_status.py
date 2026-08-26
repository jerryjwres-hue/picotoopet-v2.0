"""Model-runner outcomes must be durable enough for Core reliability diagnostics."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from picotoopet_core.ollama.model_runner import (
    IsolatedModelRunner,
    ModelRunnerPolicy,
    ModelRunnerStatus,
    ModelRunnerTimeoutError,
)

_FIXTURE = Path(__file__).parents[2] / "fixtures" / "ollama" / "fake_model_runner_child.py"


def test_timeout_and_recovery_are_atomically_projected_to_fixed_status_file(
    tmp_path: Path,
) -> None:
    work_root = tmp_path / "model-runner"
    timeout_runner = IsolatedModelRunner(
        work_root=work_root,
        model_name="gpt-oss:20b",
        base_url="http://127.0.0.1:11434/v1",
        policy=ModelRunnerPolicy(
            hard_timeout_seconds=1.0,
            max_attempts=1,
            poll_seconds=0.02,
            terminate_grace_seconds=0.2,
        ),
        child_command=(sys.executable, str(_FIXTURE), "--mode", "hang"),
    )

    with pytest.raises(ModelRunnerTimeoutError):
        timeout_runner.analyze("bounded prompt")

    status_path = work_root / "status.json"
    timed_out = ModelRunnerStatus.model_validate_json(status_path.read_bytes())
    assert timed_out.outcome == "timeout"
    assert timed_out.consecutive_failures == 1
    assert timed_out.circuit_open is False

    recovery_runner = IsolatedModelRunner(
        work_root=work_root,
        model_name="gpt-oss:20b",
        base_url="http://127.0.0.1:11434/v1",
        policy=ModelRunnerPolicy(max_attempts=1, hard_timeout_seconds=2.0),
        child_command=(sys.executable, str(_FIXTURE), "--mode", "success"),
    )
    recovery_runner.analyze("bounded prompt")

    recovered = ModelRunnerStatus.model_validate_json(status_path.read_bytes())
    assert recovered.outcome == "success"
    assert recovered.consecutive_failures == 0
    assert recovered.circuit_open is False
