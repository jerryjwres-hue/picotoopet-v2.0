"""Isolated, deadline-bounded local Ollama model execution."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from picotoopet_core.agents.models import AgentResult
from picotoopet_core.agents.runtime import build_ollama_agent

_MAX_CHILD_RESULT_BYTES = 64 * 1024


class ModelRunnerError(RuntimeError):
    """Base class for bounded local-model runner failures."""


class ModelRunnerRequestError(ModelRunnerError):
    """Trusted caller supplied an invalid or over-bounded runner request."""


class ModelRunnerTimeoutError(ModelRunnerError):
    """One isolated model attempt crossed its hard deadline."""


class ModelRunnerResultInvalidError(ModelRunnerError):
    """Child result was missing, oversized or failed strict AgentResult validation."""


class ModelRunnerExecutionError(ModelRunnerError):
    """The isolated child exited unsuccessfully without a valid result."""


class ModelRunnerCircuitOpenError(ModelRunnerError):
    """Recent failed calls opened the local-model circuit breaker."""


class ModelRunnerPolicy(BaseModel):
    """Frozen parent-owned safety policy; queue payloads never construct this model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    hard_timeout_seconds: float = Field(default=900.0, ge=1.0, le=1800.0)
    max_attempts: int = Field(default=2, ge=1, le=2)
    poll_seconds: float = Field(default=0.1, ge=0.01, le=1.0)
    terminate_grace_seconds: float = Field(default=2.0, ge=0.05, le=5.0)
    circuit_failure_threshold: int = Field(default=2, ge=1, le=5)
    circuit_cooldown_seconds: float = Field(default=60.0, ge=1.0, le=600.0)
    max_prompt_chars: int = Field(default=32_000, ge=1_000, le=64_000)
    max_result_bytes: int = Field(default=_MAX_CHILD_RESULT_BYTES, ge=1_024, le=256 * 1024)


class ModelRunnerStatus(BaseModel):
    """Sanitized durable outcome projected for Core reliability diagnostics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="1.0", pattern=r"^1\.0$")
    outcome: str = Field(
        pattern=r"^(success|timeout|result_invalid|execution_error|circuit_open)$"
    )
    consecutive_failures: int = Field(ge=0, le=1_000_000)
    circuit_open: bool
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class _ChildRequest(BaseModel):
    """Internal request file; prompt is never placed in argv or child stdout."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="1.0", pattern=r"^1\.0$")
    model_name: str = Field(min_length=1, max_length=200)
    base_url: str = Field(min_length=1, max_length=500)
    prompt: str = Field(min_length=1, max_length=64_000)


class IsolatedModelRunner:
    """Run each long model call in a killable child process with bounded retries."""

    def __init__(
        self,
        *,
        work_root: Path | str,
        model_name: str,
        base_url: str,
        policy: ModelRunnerPolicy | None = None,
        child_command: tuple[str, ...] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not model_name.strip() or len(model_name) > 200:
            raise ValueError("model_name must be 1-200 characters")
        self.base_url      = _validate_loopback_base_url(base_url)
        self.model_name    = model_name.strip()
        self.work_root     = Path(work_root).expanduser().resolve()
        self.policy        = policy or ModelRunnerPolicy()
        self.child_command = child_command or (
            sys.executable,
            "-m",
            "picotoopet_core.ollama.model_runner",
            "--child",
        )
        if not self.child_command:
            raise ValueError("child_command must not be empty")
        self._monotonic = monotonic
        self._consecutive_failures = 0
        self._circuit_open_until: float | None = None
        self.last_pid: int | None = None

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    @property
    def status_path(self) -> Path:
        """Return the one fixed sanitized status projection path."""

        return self.work_root / "status.json"

    def analyze(self, prompt: str) -> AgentResult:
        """Return one validated result or a stable bounded failure without hanging Worker."""

        if not isinstance(prompt, str) or not prompt.strip():
            raise ModelRunnerRequestError("MODEL_RUNNER_REQUEST_INVALID: prompt is required")
        if len(prompt) > self.policy.max_prompt_chars:
            raise ModelRunnerRequestError("MODEL_RUNNER_REQUEST_INVALID: prompt exceeds bound")
        try:
            self._ensure_circuit_available()
        except ModelRunnerCircuitOpenError:
            self._write_status("circuit_open")
            raise

        last_error: ModelRunnerError | None = None
        for _attempt in range(1, self.policy.max_attempts + 1):
            try:
                result = self._run_attempt(prompt)
            except ModelRunnerError as error:
                last_error = error
                continue
            self._consecutive_failures = 0
            self._circuit_open_until = None
            self._write_status("success")
            return result

        assert last_error is not None
        self._record_failed_call()
        self._write_status(_status_outcome(last_error))
        raise last_error

    def _ensure_circuit_available(self) -> None:
        if self._circuit_open_until is None:
            return
        now = self._monotonic()
        if now < self._circuit_open_until:
            raise ModelRunnerCircuitOpenError("MODEL_RUNNER_CIRCUIT_OPEN")
        # ── Cooldown expiry permits exactly the next normal call as a half-open probe. ──
        self._circuit_open_until = None

    def _record_failed_call(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.policy.circuit_failure_threshold:
            self._circuit_open_until = self._monotonic() + self.policy.circuit_cooldown_seconds

    def _write_status(self, outcome: str) -> None:
        status = ModelRunnerStatus(
            outcome=outcome,
            consecutive_failures=self._consecutive_failures,
            circuit_open=self._circuit_open_until is not None,
        )
        _write_status_atomic(self.status_path, status)

    def _run_attempt(self, prompt: str) -> AgentResult:
        self.work_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="attempt-", dir=self.work_root) as temporary:
            attempt_dir  = Path(temporary)
            request_path = attempt_dir / "request.json"
            output_path  = attempt_dir / "result.json"
            request = _ChildRequest(
                model_name=self.model_name,
                base_url=self.base_url,
                prompt=prompt,
            )
            request_path.write_text(request.model_dump_json(), encoding="utf-8")
            with suppress(OSError):
                request_path.chmod(0o600)

            command = [
                *self.child_command,
                "--request",
                str(request_path),
                "--output",
                str(output_path),
            ]
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=os.name == "posix",
            )
            self.last_pid = process.pid
            started = self._monotonic()
            try:
                while process.poll() is None:
                    if self._monotonic() - started >= self.policy.hard_timeout_seconds:
                        self._terminate(process)
                        raise ModelRunnerTimeoutError("MODEL_RUNNER_TIMEOUT")
                    time.sleep(self.policy.poll_seconds)

                if process.returncode != 0:
                    raise ModelRunnerExecutionError("MODEL_RUNNER_FAILED")
                return self._validate_output(output_path)
            finally:
                if process.poll() is None:
                    self._terminate(process)
                else:
                    process.wait(timeout=self.policy.terminate_grace_seconds)

    def _validate_output(self, output_path: Path) -> AgentResult:
        if not output_path.is_file():
            raise ModelRunnerResultInvalidError("MODEL_RUNNER_RESULT_INVALID")
        try:
            size = output_path.stat().st_size
        except OSError as error:
            raise ModelRunnerResultInvalidError("MODEL_RUNNER_RESULT_INVALID") from error
        if size <= 0 or size > self.policy.max_result_bytes:
            output_path.unlink(missing_ok=True)
            raise ModelRunnerResultInvalidError("MODEL_RUNNER_RESULT_INVALID")
        try:
            return AgentResult.model_validate_json(output_path.read_bytes())
        except (OSError, ValidationError, ValueError) as error:
            output_path.unlink(missing_ok=True)
            raise ModelRunnerResultInvalidError("MODEL_RUNNER_RESULT_INVALID") from error

    def _terminate(self, process: subprocess.Popen[bytes]) -> None:
        """Terminate the whole child process group, escalate, and always reap it."""

        if process.poll() is not None:
            process.wait(timeout=self.policy.terminate_grace_seconds)
            return
        if os.name == "posix":
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        try:
            process.wait(timeout=self.policy.terminate_grace_seconds)
            return
        except subprocess.TimeoutExpired:
            pass
        if os.name == "posix":
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=self.policy.terminate_grace_seconds)


def _status_outcome(error: ModelRunnerError) -> str:
    if isinstance(error, ModelRunnerTimeoutError):
        return "timeout"
    if isinstance(error, ModelRunnerResultInvalidError):
        return "result_invalid"
    if isinstance(error, ModelRunnerCircuitOpenError):
        return "circuit_open"
    return "execution_error"


def _validate_loopback_base_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme != "http" or parsed.username or parsed.password or not parsed.hostname:
        raise ValueError("model runner endpoint must be loopback HTTP")
    host = parsed.hostname.rstrip(".").lower()
    if host not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("model runner endpoint must be loopback")
    if parsed.query or parsed.fragment:
        raise ValueError("model runner endpoint cannot contain query or fragment")
    port = f":{parsed.port}" if parsed.port is not None else ""
    host_text = f"[{host}]" if ":" in host else host
    path = parsed.path.rstrip("/")
    return f"http://{host_text}{port}{path}"


def _write_status_atomic(status_path: Path, status: ModelRunnerStatus) -> None:
    data = status.model_dump_json().encode("utf-8")
    status_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".model-status-",
        dir=status_path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        with suppress(OSError):
            temporary.chmod(0o600)
        os.replace(temporary, status_path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_result_atomic(output_path: Path, result: AgentResult) -> None:
    data = result.model_dump_json().encode("utf-8")
    if len(data) > _MAX_CHILD_RESULT_BYTES:
        raise ValueError("model result too large")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".model-result-",
        dir=output_path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output_path)
    finally:
        temporary.unlink(missing_ok=True)


def _run_child(args: argparse.Namespace) -> int:
    """Execute only the trusted internal request file and emit no stdout/stderr payload."""

    try:
        request = _ChildRequest.model_validate_json(Path(args.request).read_bytes())
        base_url = _validate_loopback_base_url(request.base_url)
        runtime = build_ollama_agent(model_name=request.model_name, base_url=base_url)
        result = asyncio.run(runtime.analyze(request.prompt))
        _write_result_atomic(Path(args.output), result)
        return 0
    except Exception:  # noqa: BLE001 - child exposes only its bounded exit code to parent
        return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--request")
    parser.add_argument("--output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if not args.child or not args.request or not args.output:
        return 2
    return _run_child(args)


if __name__ == "__main__":
    raise SystemExit(main())
