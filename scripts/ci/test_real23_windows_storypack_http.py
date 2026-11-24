"""CPU-only Windows CI: real Python 2.3 FastAPI ↔ existing C# Studio HTTP client."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from contextlib import closing
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


def _assert_sandbox_scoped_goal(db_path: Path) -> None:
    """使用 query_only 核对唯一显式 Goal，拒绝任何执行/审批/生产写入。"""

    if not db_path.is_file():
        raise RuntimeError("REAL_CORE_DATABASE_MISSING")
    # sqlite3 Connection 的 context manager 不负责 close；Windows 必须显式释放文件句柄。
    with closing(sqlite3.connect(str(db_path))) as db:
        db.execute("PRAGMA query_only=ON")
        maximum = db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        if maximum != 24:
            raise RuntimeError(f"REAL_CORE_SCHEMA_UNEXPECTED:{maximum}")
        for table in ("approvals", "production_jobs", "production_attempts", "creative_jobs"):
            count = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if count != 0:
                raise RuntimeError(f"READ_ONLY_VIOLATION:{table}:{count}")
        # 只读阶段已在客户端证明 TASK_DELTA=0；后续显式确认只允许一个 local Goal。
        goals = db.execute("SELECT goal_id,workflow_id,intent_type,constraints_json FROM autonomous_goals").fetchall()
        if len(goals) != 1 or goals[0][2] != "video.creative" or not goals[0][1]:
            raise RuntimeError("STUDIO_SCOPED_GOAL_REPLAY_MISMATCH")
        constraints = json.loads(goals[0][3])
        binding = constraints["storypack_binding"]
        if (constraints.get("local_video_preferred") is not True
            or constraints.get("read_only_research") is not True
            or binding.get("owner_subject_key") != "pet:ci-fixture"
            or len(binding.get("dynamic_motion_digest", "")) != 64):
            raise RuntimeError("STUDIO_SCOPED_GOAL_CONSTRAINT_MISMATCH")
        if db.execute("SELECT COUNT(*) FROM canonical_evidence").fetchone()[0] != 3:
            raise RuntimeError("STUDIO_OWNER_PACKET_REPLAY_MISMATCH")
        for task in db.execute("SELECT task_type,resource_tag,attempt_count,lease_owner FROM tasks"):
            if (task[0] not in {"autonomous.discovery.v1", "autonomous.goal_synthesis.v1",
                                "autonomous.goal_creative.v1"}
                or task[1] != f"workflow:{goals[0][1]}"
                or task[2] != 0 or task[3] is not None):
                raise RuntimeError("STUDIO_UNEXPECTED_EXECUTION")
        # 01. 保留原有三份 Core 托管副本，同时精确核对新增的
        #     Windows-only LoRA 摘要声明：不能把它算成第四份 Core 验证文件。
        rows = db.execute(
            "SELECT artifact_type, sha256, stored_object_hash, size_bytes, "
            "is_original, cloud_policy, source_path FROM artifacts"
        ).fetchall()
        required = {
            "storypack_character", "storypack_scene", "storypack_style", "storypack_lora",
        }
        if len(rows) != 4 or {row[0] for row in rows} != required:
            raise RuntimeError("STUDIO_ASSET_SCOPE_OR_REPLAY_MISMATCH")

        lora_fixture = b"ci-fixture-lora-metadata-only"
        lora_digest = hashlib.sha256(lora_fixture).hexdigest()
        for kind, digest, stored_hash, size, original, policy, source_path in rows:
            # 02. Windows LoRA 只能拥有 SHA 声明，不能出现受信任副本或私有路径。
            if kind == "storypack_lora":
                if (digest != lora_digest or size != len(lora_fixture)
                    or stored_hash is not None or source_path is not None
                    or original != 0 or policy != "local_only"):
                    raise RuntimeError("STUDIO_LORA_CLAIM_NOT_CORE_VERIFIED_MISMATCH")
                continue

            # 03. 既有三类资产仍须由 Core 本机读取真正的托管字节，
            #     证明源文件没有被 LoRA 声明替代或混入其他类型。
            if (kind not in {"storypack_character", "storypack_scene", "storypack_style"}
                or digest != stored_hash or source_path is not None
                or original != 0 or policy != "local_only"):
                raise RuntimeError("STUDIO_ASSET_TRUST_FIELDS_INVALID")
            obj = db_path.parent.parent / "results" / "objects" / digest[:2] / digest[2:]
            data = obj.read_bytes()
            if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
                raise RuntimeError("STUDIO_ASSET_MANAGED_BYTES_MISMATCH")
        if db.execute("SELECT COUNT(*) FROM projects").fetchone()[0] != 1:
            raise RuntimeError("STUDIO_PROJECT_SCOPE_MISMATCH")


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
                # 显式创建唯一的临时测试项目；不使用真实用户项目。
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/v1/projects",
                    data=json.dumps({
                        "title": "CI asset registration fixture",
                        "project_type": "film",
                        "source_app": "test",
                        "classification": "INTERNAL",
                    }).encode("utf-8"),
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=10) as response:
                    env["PICOTOO_TEST_STUDIO_PROJECT"] = json.load(response)["project_id"]
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
                if "REAL_CORE_WINDOWS_ASSET_HTTP=PASS" not in call.stdout:
                    raise RuntimeError("WINDOWS_REAL_ASSET_HTTP_MISSING_PROOF")
                if "REAL_CORE_WINDOWS_SCOPED_GOAL_HTTP=PASS" not in call.stdout:
                    raise RuntimeError("WINDOWS_REAL_SCOPED_GOAL_MISSING_PROOF")
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)
                # 失败时保留真实 Python 服务端诊断；仅限本次 CI 临时实例。
                if sys.exc_info()[0] is not None:
                    log.flush()
                    diagnostic = output.read_bytes()[-24000:].decode("utf-8", errors="replace")
                    diagnostic = diagnostic.replace(token, "[REDACTED_TEST_TOKEN]")
                    print("=== CI SANDBOX CORE LOG TAIL ===", file=sys.stderr)
                    print(diagnostic, file=sys.stderr)

        _assert_sandbox_scoped_goal(root / "core-runtime" / "database" / "core.db")

    # 上游两端没有借用用户私有服务器，也未授予正式的 GPU/Owner 许可。
    print("REAL_23_WINDOWS_HTTP=PASS; SQLITE_V24=PASS; READONLY_TASK_DELTA=0; SCOPED_GOAL=1; APPROVAL=0; PRODUCTION=0")
    print("REAL_ASSET_HTTP=PASS; CORE_COPIES=3; LORA_WINDOWS_CLAIMS=1; MANAGED_SHA256=PASS; REPLAY=PASS")
    print("REAL_SCOPED_GOAL_HTTP=PASS; EVIDENCE_PACKETS=1; GOAL_REPLAY=PASS; EXECUTED_TASKS=0")
    print("WORKER=NOT_STARTED; COMFY=NOT_STARTED; OWNER=NOT_APPROVED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
