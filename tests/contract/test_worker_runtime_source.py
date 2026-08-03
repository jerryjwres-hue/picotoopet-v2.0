"""Worker Runtime 源码和交付边界合同。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "picotoopet_core"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_worker_cli_is_explicit_and_not_started_by_serve() -> None:
    """Worker 必须由独立命令启动，API serve 不得隐式启动。"""

    cli = read(SRC / "cli.py")
    assert 'commands.add_parser("worker"' in cli
    assert 'arguments.command == "worker"' in cli
    assert "WorkerRuntime" in cli
    serve_block = cli.split('if arguments.command == "serve":', maxsplit=1)[1].split(
        'if arguments.command == "health":', maxsplit=1
    )[0]
    assert "WorkerRuntime" not in serve_block
    assert "lease_next" not in serve_block


def test_worker_registry_is_closed_and_supports_only_frozen_local_types() -> None:
    """Slice D 只允许 noop 与诊断任务，不得动态发现或误支持 analysis。"""

    handlers = read(SRC / "worker" / "handlers.py")
    assert '"system.noop"' in handlers
    assert '"system.diagnostic_snapshot"' in handlers
    assert '"analysis"' not in handlers
    assert "importlib" not in handlers
    assert "entry_points" not in handlers
    assert "subprocess" not in handlers
    assert "urllib" not in handlers
    assert "requests" not in handlers


def test_worker_runtime_uses_owner_guarded_queue_operations() -> None:
    """Runtime 不得绕过租约所有权直接调用通用 transition。"""

    runtime = read(SRC / "worker" / "runtime.py")
    for required in (
        "supported_task_types",
        "lease_next",
        "renew_lease",
        "complete_leased",
        "complete_leased_with_result",
        "cancel_leased",
        "fail_leased",
        "recover_expired_supported_leases",
        "promote_retries",
        "LeaseHeartbeat",
    ):
        assert required in runtime
    assert ".transition(" not in runtime
    assert "self.queue.recover_expired_leases()" not in runtime


def test_worker_status_is_read_from_atomic_state_store() -> None:
    """API 只能读取状态文件，不得因为查询状态而启动 Worker。"""

    route = read(SRC / "api" / "routes" / "workers.py")
    state = read(SRC / "worker" / "state.py")
    assert "worker_state.read_status" in route
    assert "os.replace" in state
    assert "worker-status.json" in state
    assert "lease_next" not in route
    assert "WorkerRuntime" not in route


def test_worker_allows_only_the_bounded_diagnostic_subprocess_runner() -> None:
    """Worker 只能调用经过专门超时、取消和进程组清理的诊断 runner。"""

    runtime = read(SRC / "worker" / "runtime.py")
    runner = read(SRC / "diagnostics" / "subprocess_runner.py")
    worker_root = SRC / "worker"
    combined = "\n".join(read(path) for path in worker_root.glob("*.py") if path.is_file())

    assert "from picotoopet_core.diagnostics.subprocess_runner import" in runtime
    assert "DiagnosticSubprocessRunner" in runtime
    assert "start_new_session=os.name == \"posix\"" in runner
    assert "os.killpg(process.pid, signal.SIGTERM)" in runner
    assert "os.killpg(process.pid, signal.SIGKILL)" in runner
    assert "terminate_grace_seconds" in runner

    for forbidden in (
        "import subprocess",
        "from subprocess",
        "subprocess.Popen",
        "os.system",
        "requests.",
        "httpx.",
        "urllib.",
        "OpenAI",
        "Anthropic",
        "ComfyUI",
        "upload",
        'lease_next("analysis"',
    ):
        assert forbidden not in combined
