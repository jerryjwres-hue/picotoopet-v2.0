"""Provider 专用的有界子进程运行器。"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Sequence


class BoundedProcessError(RuntimeError):
    """Provider 子进程未能在固定边界内完成。"""


class BoundedProcessTimeout(BoundedProcessError):
    """Provider 子进程达到固定墙钟上限。"""


class BoundedProcessCancelled(BoundedProcessError):
    """Provider 子进程收到取消请求。"""


class BoundedProcessOutputLimit(BoundedProcessError):
    """Provider 子进程输出超过固定上限。"""


@dataclass(frozen=True, slots=True)
class BoundedProcessResult:
    """不包含命令字符串或环境变量的有界结果。"""

    return_code: int
    stdout: str
    stderr: str
    elapsed_seconds: int


class BoundedProcessRunner:
    """以独立进程组运行一个由调用方代码固定构造的 argv。"""

    _READ_CHUNK = 16 * 1024
    _POLL_SECONDS = 0.05
    _TERMINATE_GRACE_SECONDS = 5.0

    def run(
        self,
        *,
        argv: Sequence[str],
        cwd: Path,
        stdin_text: str,
        timeout_seconds: int,
        output_limit_bytes: int,
        cancel_event: threading.Event | None = None,
    ) -> BoundedProcessResult:
        """执行固定 argv，限制时间、输出并在停止时终止完整进程组。"""

        if not argv or any(not isinstance(value, str) or not value for value in argv):
            raise BoundedProcessError("Provider argv 无效。")
        if timeout_seconds < 1 or output_limit_bytes < 1:
            raise BoundedProcessError("Provider 运行边界无效。")
        working_directory = cwd.expanduser().resolve(strict=True)
        if not working_directory.is_dir() or working_directory.is_symlink():
            raise BoundedProcessError("Provider 工作目录无效。")

        process = subprocess.Popen(
            list(argv),
            cwd=working_directory,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._safe_environment(),
            start_new_session=os.name == "posix",
            shell=False,
        )
        if process.stdin is None or process.stdout is None or process.stderr is None:
            self._terminate_process_group(process)
            raise BoundedProcessError("Provider 标准流不可用。")

        stdout = bytearray()
        stderr = bytearray()
        overflow = threading.Event()

        def read_stream(stream: object, target: bytearray) -> None:
            reader = stream
            while True:
                chunk = reader.read(self._READ_CHUNK)  # type: ignore[attr-defined]
                if not chunk:
                    return
                if len(target) + len(chunk) > output_limit_bytes:
                    overflow.set()
                    return
                target.extend(chunk)

        stdout_thread = threading.Thread(
            target=read_stream,
            args=(process.stdout, stdout),
            name="picotoopet-provider-stdout",
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=read_stream,
            args=(process.stderr, stderr),
            name="picotoopet-provider-stderr",
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()

        try:
            process.stdin.write(stdin_text.encode("utf-8"))
            process.stdin.close()
            started = monotonic()
            while process.poll() is None:
                if overflow.is_set():
                    self._terminate_process_group(process)
                    raise BoundedProcessOutputLimit("Provider 输出超过固定上限。")
                if cancel_event is not None and cancel_event.wait(self._POLL_SECONDS):
                    self._terminate_process_group(process)
                    raise BoundedProcessCancelled("Provider Session 已取消。")
                if monotonic() - started >= timeout_seconds:
                    self._terminate_process_group(process)
                    raise BoundedProcessTimeout("Provider Session 达到固定时间上限。")
                if cancel_event is None:
                    threading.Event().wait(self._POLL_SECONDS)

            stdout_thread.join(timeout=self._TERMINATE_GRACE_SECONDS)
            stderr_thread.join(timeout=self._TERMINATE_GRACE_SECONDS)
            if overflow.is_set():
                raise BoundedProcessOutputLimit("Provider 输出超过固定上限。")
            if stdout_thread.is_alive() or stderr_thread.is_alive():
                self._terminate_process_group(process)
                raise BoundedProcessError("Provider 输出流未能关闭。")
            try:
                decoded_stdout = bytes(stdout).decode("utf-8", errors="strict")
                decoded_stderr = bytes(stderr).decode("utf-8", errors="strict")
            except UnicodeDecodeError as error:
                raise BoundedProcessError("Provider 输出不是有效 UTF-8。") from error
            return BoundedProcessResult(
                return_code=int(process.returncode or 0),
                stdout=decoded_stdout,
                stderr=decoded_stderr,
                elapsed_seconds=min(int(monotonic() - started), timeout_seconds),
            )
        finally:
            if process.poll() is None:
                self._terminate_process_group(process)
            stdout_thread.join(timeout=self._TERMINATE_GRACE_SECONDS)
            stderr_thread.join(timeout=self._TERMINATE_GRACE_SECONDS)

    @staticmethod
    def _safe_environment() -> dict[str, str]:
        """只继承 Codex 本机登录和基础运行所需的固定环境名。"""

        allowed = ("HOME", "PATH", "TMPDIR", "LANG", "LC_ALL", "SHELL")
        environment = {
            key: value
            for key in allowed
            if (value := os.environ.get(key)) is not None
        }
        environment["NO_COLOR"] = "1"
        return environment

    @classmethod
    def _terminate_process_group(cls, process: subprocess.Popen[bytes]) -> None:
        """终止完整进程组；平台不支持时保守终止直接子进程。"""

        if process.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            process.wait(timeout=cls._TERMINATE_GRACE_SECONDS)
            return
        except (ProcessLookupError, subprocess.TimeoutExpired):
            pass
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            return
        process.wait(timeout=cls._TERMINATE_GRACE_SECONDS)
