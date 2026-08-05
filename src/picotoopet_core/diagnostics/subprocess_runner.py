"""可终止、可取消的诊断采集子进程协议。"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

from .collector import collect_snapshot
from .models import (
    DiagnosticFacts,
    DiagnosticSnapshotRequest,
    DiagnosticSnapshotResult,
)

_MAX_RESULT_BYTES = 64 * 1024


class DiagnosticSubprocessError(RuntimeError):
    """诊断子进程受控错误基类。"""


class DiagnosticCollectionError(DiagnosticSubprocessError):
    """子进程返回失败或没有产生有效候选结果。"""


class DiagnosticTimeoutError(DiagnosticSubprocessError):
    """子进程超过冻结硬超时。"""


class DiagnosticCancelledError(DiagnosticSubprocessError):
    """父 Worker 观察到取消意图并终止子进程。"""


class DiagnosticResultInvalidError(DiagnosticSubprocessError):
    """候选结果大小或严格模型验证失败。"""


class DiagnosticSubprocessRunner:
    """父进程持有租约，子进程只生成受限候选 JSON。"""

    def __init__(
        self,
        *,
        poll_seconds: float = 0.1,
        terminate_grace_seconds: float = 5.0,
    ) -> None:
        if poll_seconds <= 0:
            raise ValueError("poll_seconds 必须大于 0。")
        if terminate_grace_seconds <= 0 or terminate_grace_seconds > 5:
            raise ValueError("terminate_grace_seconds 必须位于 0 到 5 秒。")
        self.poll_seconds = poll_seconds
        self.terminate_grace_seconds = terminate_grace_seconds
        self.last_pid: int | None = None

    def run(
        self,
        request: DiagnosticSnapshotRequest,
        facts: DiagnosticFacts,
        *,
        output_dir: Path | str,
        timeout_seconds: float,
        cancel_requested: Callable[[], bool],
        test_delay_seconds: float = 0,
        test_fail: bool = False,
    ) -> Path:
        """执行一次子进程；任何退出路径都等待或强制回收进程。"""

        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须大于 0。")
        destination_dir = Path(output_dir).expanduser().resolve()
        destination_dir.mkdir(parents=True, exist_ok=True)
        request_path = destination_dir / "diagnostic-request.json"
        facts_path = destination_dir / "diagnostic-facts.json"
        output_path = destination_dir / "diagnostic-result.json"
        output_path.unlink(missing_ok=True)
        request_path.write_text(
            request.model_dump_json(),
            encoding="utf-8",
        )
        facts_path.write_text(
            facts.model_dump_json(),
            encoding="utf-8",
        )

        command = [
            sys.executable,
            "-m",
            "picotoopet_core.diagnostics.subprocess_runner",
            "--child",
            "--request",
            str(request_path),
            "--facts",
            str(facts_path),
            "--output",
            str(output_path),
        ]
        if test_delay_seconds:
            command.extend(["--test-delay-seconds", str(test_delay_seconds)])
        if test_fail:
            command.append("--test-fail")

        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=os.name == "posix",
        )
        self.last_pid = process.pid
        started = time.monotonic()
        try:
            while process.poll() is None:
                if cancel_requested():
                    self._terminate(process)
                    raise DiagnosticCancelledError("诊断任务已取消。")
                if time.monotonic() - started >= timeout_seconds:
                    self._terminate(process)
                    raise DiagnosticTimeoutError("诊断任务超过硬超时。")
                time.sleep(self.poll_seconds)

            if process.returncode != 0:
                raise DiagnosticCollectionError("诊断采集子进程失败。")
            return self._validate_output(output_path)
        finally:
            if process.poll() is None:
                self._terminate(process)
            else:
                process.wait(timeout=self.terminate_grace_seconds)

    def _validate_output(self, output_path: Path) -> Path:
        if not output_path.is_file():
            raise DiagnosticResultInvalidError("诊断子进程没有产生结果。")
        if output_path.stat().st_size > _MAX_RESULT_BYTES:
            output_path.unlink(missing_ok=True)
            raise DiagnosticResultInvalidError("诊断结果超过 64 KiB。")
        try:
            DiagnosticSnapshotResult.model_validate_json(output_path.read_bytes())
        except Exception as error:
            output_path.unlink(missing_ok=True)
            raise DiagnosticResultInvalidError("诊断结果合同验证失败。") from error
        return output_path

    def _terminate(self, process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            process.wait(timeout=self.terminate_grace_seconds)
            return
        if os.name == "posix":
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        try:
            process.wait(timeout=self.terminate_grace_seconds)
            return
        except subprocess.TimeoutExpired:
            pass
        if os.name == "posix":
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=self.terminate_grace_seconds)


def _write_candidate_atomic(output_path: Path, document: dict[str, object]) -> None:
    data = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(data) > _MAX_RESULT_BYTES:
        raise ValueError("candidate too large")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".diagnostic-result-",
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
    try:
        if args.test_delay_seconds > 0:
            time.sleep(args.test_delay_seconds)
        if args.test_fail:
            raise RuntimeError("injected child failure")
        request = DiagnosticSnapshotRequest.model_validate_json(
            Path(args.request).read_bytes()
        )
        facts = DiagnosticFacts.model_validate_json(Path(args.facts).read_bytes())
        result = collect_snapshot(request, facts)
        _write_candidate_atomic(
            Path(args.output),
            result.model_dump(mode="json"),
        )
        return 0
    except Exception:
        return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--request")
    parser.add_argument("--facts")
    parser.add_argument("--output")
    parser.add_argument("--test-delay-seconds", type=float, default=0.0)
    parser.add_argument("--test-fail", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if not args.child or not args.request or not args.facts or not args.output:
        return 2
    return _run_child(args)


if __name__ == "__main__":
    raise SystemExit(main())
