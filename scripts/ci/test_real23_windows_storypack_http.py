"""CPU-only Windows CI: real Python 2.3 FastAPI ↔ existing C# Studio HTTP client."""

from __future__ import annotations

import os
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

# 本脚本只在 CI 临时目录启动真实 Core；不连接用户 Mac/Windows/Comfy。
ROOT = Path(__file__).resolve().parents[2]
CLIENT_PROJECT = (
    ROOT
    / "windows"
    / "desktop"
    / "tests"
    / "PicotooPet.Desktop.Core.SmokeTests"
    / "PicotooPet.Desktop.Core.SmokeTests.csproj"
)


def _available_local_port() -> int:
    """只使用回环地址绑定空闲测试端口，永不使用用户 Mac 的 8765/8766。"""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_core(port: int, process: subprocess.Popen[bytes]) -> None:
    """启动后只轮询真实 HTTP 健康状态；不使用任何伪 Core 响应。"""

    url = f"http://127.0.0.1:{port}/api/v1/health"
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("REAL_CORE_EXITED_EARLY")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200 and b'"database":"ok"' in response.read():
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.25)
    raise RuntimeError("REAL_CORE_HEALTH_TIMEOUT")


def _assert_sandbox_untouched(db_path: Path) -> None:
    """使用 query_only 读取 Core 的真实 24 版 SQLite；拒绝任何任务/审批/生产写入。"""

    if not db_path.is_file():
        raise RuntimeError("REAL_CORE_DATABASE_MISSING")
    with sqlite3.connect(str(db_path)) as db:
        db.execute("PRAGMA query_only=ON")
        maximum = db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        if maximum != 24:
            raise RuntimeError(f"REAL_CORE_SCHEMA_UNEXPECTED:{maximum}")
        for table in ("tasks", "approvals", "production_jobs"):
            count = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if count != 0:
                raise RuntimeError(f"READ_ONLY_VIOLATION:{table}:{count}")


def main() -> int:
    """真实 Core 进程启动 → Windows 客户端调用 → 进程回收 → SQLite 只读核对。"""

    if sys.platform != "win32":
        raise RuntimeError("NATIVE_WINDOWS_ONLY")
    if not CLIENT_PROJECT.is_file():
        raise RuntimeError("STUDIO_CLIENT_PROJECT_MISSING")

    with tempfile.TemporaryDirectory(prefix="picotoo-studio-interop-") as home:
        root = Path(home)
        port = _available_local_port()
        token = secrets.token_urlsafe(36)
        env = os.environ.copy()
        env.update(
            {
                "PICOTOO_RUNTIME_ROOT": str(root / "core-runtime"),
                "PICOTOO_API_HOST": "127.0.0.1",
                "PICOTOO_API_PORT": str(port),
                "PICOTOO_API_TOKEN": token,
                "PICOTOO_TEST_STUDIO_PORT": str(port),
                "PICOTOO_TEST_STUDIO_TOKEN": token,
                "PICOTOO_PROTECTED_ROOTS": "",
                "PICOTOO_OWNER_REVIEW_REGISTRY_FILE": "",
            }
        )
        output = root / "core-stdout.log"
        with output.open("wb") as log:
            # 独立真实 Core，仅启动 serve，不启动 worker/supervise 和 Comfy。
            proc = subprocess.Popen(
                [sys.executable, "-m", "picotoopet_core.cli", "serve"],
                cwd=ROOT,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                _wait_for_core(port, proc)
                # 与已编译的原生 C# 客户端实际通过 localhost HTTP 相互操作。
                call = subprocess.run(
                    [
                        "dotnet",
                        "run",
                        "--project",
                        str(CLIENT_PROJECT),
                        "--configuration",
                        "Release",
                        "--no-build",
                        "--",
                        "--studio-storypack-live-only",
                    ],
                    cwd=ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=70,
                    check=False,
                )
                if call.returncode != 0:
                    print(call.stdout[-4000:])
                    print(call.stderr[-4000:], file=sys.stderr)
                    raise RuntimeError(f"WINDOWS_REAL_HTTP_CLIENT_FAILED:{call.returncode}")
                if "REAL_CORE_WINDOWS_STUDIO_HTTP=PASS" not in call.stdout:
                    raise RuntimeError("WINDOWS_REAL_HTTP_MISSING_PROOF")
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)

        _assert_sandbox_untouched(root / "core-runtime" / "database" / "core.db")

    # 上游两端没有借用用户私有服务器，也未授予正式的 GPU/Owner 许可。
    print("REAL_23_WINDOWS_HTTP=PASS; SQLITE_V24=PASS; TASK=0; APPROVAL=0; PRODUCTION=0")
    print("WORKER=NOT_STARTED; COMFY=NOT_STARTED; OWNER=NOT_APPROVED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
