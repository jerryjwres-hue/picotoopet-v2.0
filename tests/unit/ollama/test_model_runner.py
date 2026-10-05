"""Local model work must be isolated, deadline-bounded and circuit-broken."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from picotoopet_core.ollama.model_runner import (
    IsolatedModelRunner,
    ModelRunnerCircuitOpenError,
    ModelRunnerPolicy,
    ModelRunnerRequestError,
    ModelRunnerResultInvalidError,
    ModelRunnerTimeoutError,
)

_FIXTURE = Path(__file__).parents[2] / "fixtures" / "ollama" / "fake_model_runner_child.py"


class MutableClock:
    """Small deterministic monotonic clock for circuit-breaker cooldown tests."""

    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _runner(
    tmp_path: Path,
    *,
    mode: str,
    counter: Path | None = None,
    policy: ModelRunnerPolicy | None = None,
    clock: MutableClock | None = None,
) -> IsolatedModelRunner:
    command = [sys.executable, str(_FIXTURE), "--mode", mode]
    if counter is not None:
        command.extend(["--counter", str(counter)])
    return IsolatedModelRunner(
        work_root=tmp_path / "model-runner",
        model_name="gpt-oss:20b",
        base_url="http://127.0.0.1:11434/v1",
        policy=policy or ModelRunnerPolicy(),
        child_command=tuple(command),
        monotonic=clock or __import__("time").monotonic,
    )


def test_policy_and_request_are_strictly_bounded_and_loopback_only(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        ModelRunnerPolicy(max_attempts=3)
    with pytest.raises(ValidationError):
        ModelRunnerPolicy(hard_timeout_seconds=0.1)
    with pytest.raises(ValueError, match="loopback"):
        IsolatedModelRunner(
            work_root=tmp_path,
            model_name="gpt-oss:20b",
            base_url="https://example.com/v1",
        )

    runner = _runner(tmp_path, mode="success")
    with pytest.raises(ModelRunnerRequestError, match="prompt"):
        runner.analyze("x" * 32_001)


def test_hard_deadline_terminates_and_reaps_hung_child(tmp_path: Path) -> None:
    runner = _runner(
        tmp_path,
        mode="hang",
        policy=ModelRunnerPolicy(
            hard_timeout_seconds=1.0,
            max_attempts=1,
            poll_seconds=0.02,
            terminate_grace_seconds=0.2,
        ),
    )

    with pytest.raises(ModelRunnerTimeoutError):
        runner.analyze("bounded prompt")

    assert runner.last_pid is not None
    if os.name == "posix":
        with pytest.raises(ProcessLookupError):
            os.kill(runner.last_pid, 0)


def test_transient_failure_retries_only_once_then_success_resets_breaker(tmp_path: Path) -> None:
    counter = tmp_path / "attempts.txt"
    runner = _runner(
        tmp_path,
        mode="fail-once",
        counter=counter,
        policy=ModelRunnerPolicy(max_attempts=2, hard_timeout_seconds=2.0),
    )

    result = runner.analyze("bounded prompt")

    assert result.summary == "fixture-result"
    assert result.confidence == 0.81
    assert counter.read_text(encoding="utf-8") == "2"
    assert runner.consecutive_failures == 0


def test_two_failed_calls_open_circuit_without_spawning_third_child(tmp_path: Path) -> None:
    counter = tmp_path / "attempts.txt"
    clock   = MutableClock()
    runner  = _runner(
        tmp_path,
        mode="fail",
        counter=counter,
        clock=clock,
        policy=ModelRunnerPolicy(
            max_attempts=1,
            hard_timeout_seconds=2.0,
            circuit_failure_threshold=2,
            circuit_cooldown_seconds=10.0,
        ),
    )

    for _ in range(2):
        with pytest.raises(RuntimeError, match="MODEL_RUNNER_FAILED"):
            runner.analyze("bounded prompt")

    assert counter.read_text(encoding="utf-8") == "2"
    with pytest.raises(ModelRunnerCircuitOpenError, match="MODEL_RUNNER_CIRCUIT_OPEN"):
        runner.analyze("bounded prompt")
    assert counter.read_text(encoding="utf-8") == "2"

    clock.advance(11.0)
    with pytest.raises(RuntimeError, match="MODEL_RUNNER_FAILED"):
        runner.analyze("bounded prompt")
    assert counter.read_text(encoding="utf-8") == "3"


def test_invalid_missing_or_oversized_results_fail_closed_without_prompt_leak(
    tmp_path: Path,
) -> None:
    secret_prompt = "PRIVATE_PROMPT_MUST_NOT_LEAK"
    for mode in ("missing", "invalid-json", "oversized"):
        runner = _runner(
            tmp_path / mode,
            mode=mode,
            policy=ModelRunnerPolicy(max_attempts=1, hard_timeout_seconds=2.0),
        )
        with pytest.raises(ModelRunnerResultInvalidError) as caught:
            runner.analyze(secret_prompt)
        assert secret_prompt not in str(caught.value)
