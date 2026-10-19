"""Issue #93: native macOS readiness smoke; all runtime paths are test-owned."""

from __future__ import annotations

import json
import os
import plistlib
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.db.database import Database
from picotoopet_core.domain.enums import TaskStatus
from picotoopet_core.domain.models import TaskCreate
from picotoopet_core.ollama.client import OllamaClient
from picotoopet_core.ollama.resident_manager import ResidentManager, ResidentStatus
from picotoopet_core.queue.diagnostic_repository import DiagnosticQueueRepository

ROOT = Path(__file__).resolve().parents[2]
WORKER_LIB = ROOT / "deploy/macos/phase23-worker/worker-lib.sh"
TOKEN = "p0-test-only-token-0123456789abcdef"


def _database(root: Path) -> tuple[Database, DiagnosticQueueRepository]:
    """Open the production schema without touching a real runtime directory."""

    database = Database(root / "database" / "core.db")
    database.open()
    database.apply_migrations()
    return database, DiagnosticQueueRepository(database)


def _await_state(queue: DiagnosticQueueRepository, expected: dict[str, TaskStatus],
                 process: subprocess.Popen[str], *, seconds: float = 35.0) -> None:
    """Bound polling by monotonic time and fail immediately on a crashed Worker."""

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        actual = {task_id: queue.get(task_id).status for task_id in expected}
        if actual == expected:
            return
        if process.poll() is not None:
            stderr = process.stderr.read() if process.stderr else ""
            pytest.fail(f"worker exited unexpectedly rc={process.returncode}: {stderr[-2000:]}")
        time.sleep(0.15)
    pytest.fail(f"bounded worker deadline exceeded; actual={actual!r}")


def _stop(process: subprocess.Popen[str]) -> None:
    """Terminate only the subprocess owned by this fixture."""

    if process.poll() is None:
        process.send_signal(signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
            pytest.fail("worker did not stop within the 10s grace period")
    assert process.returncode == 0


def _start(root: Path, worker_id: str) -> subprocess.Popen[str]:
    """Start the real CLI Worker, isolated from Ollama and the user's keychain."""

    env = os.environ.copy()
    env.update({
        "PICOTOO_RUNTIME_ROOT": str(root),
        "PICOTOO_API_TOKEN": TOKEN,
        "PICOTOO_OLLAMA_BASE_URL": "http://127.0.0.1:9",
        "PICOTOO_LOCAL_INTELLIGENCE_BASE_URL": "http://127.0.0.1:9/v1/",
        "PICOTOO_LOCAL_INTELLIGENCE_TIMEOUT_SECONDS": "1",
        "PICOTOO_WORKER_POLL_SECONDS": "0.2",
        "PICOTOO_WORKER_LEASE_SECONDS": "4",
        "PICOTOO_WORKER_HEARTBEAT_SECONDS": "1",
        "PICOTOO_WORKER_STATUS_STALE_SECONDS": "4",
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
    })
    return subprocess.Popen(
        [sys.executable, "-m", "picotoopet_core.cli", "worker", "--loop",
         "--worker-id", worker_id],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
    )


@pytest.mark.skipif(sys.platform != "darwin", reason="native macOS gate")
def test_launchd_worker_plist_has_bounded_restart_and_no_secret(tmp_path: Path) -> None:
    """Validate the *real* packaging helper and platform plist parser, no bootstrap."""

    home = tmp_path / "isolated home"
    home.mkdir()
    root = tmp_path / "isolated runtime"
    env = {**os.environ, "HOME": str(home)}
    subprocess.run(
        ["bash", "-c", 'source "$1"; write_worker_plist "$2" "p0-fixture"',
         "bash", str(WORKER_LIB), str(root)],
        check=True, env=env, capture_output=True, text=True, timeout=15,
    )
    plist = home / "Library/LaunchAgents/com.picotoopet.worker.plist"
    subprocess.run(["plutil", "-lint", str(plist)], check=True, capture_output=True)
    with plist.open("rb") as handle:
        payload = plistlib.load(handle)
    assert payload["Label"] == "com.picotoopet.worker"
    assert payload["KeepAlive"] is True
    assert payload["RunAtLoad"] is True
    assert payload["ThrottleInterval"] >= 30
    assert payload["ProcessType"] == "Background"
    assert payload["ProgramArguments"][1:3] == ["worker", "--loop"]
    assert str(root / "current/.venv/bin/picotoopet-core") == payload["ProgramArguments"][0]
    assert payload["EnvironmentVariables"]["PICOTOO_RUNTIME_ROOT"] == str(root)
    assert "PICOTOO_API_TOKEN" not in payload["EnvironmentVariables"]
    assert TOKEN not in plist.read_text(encoding="utf-8")
    # Missing runtime executable must be reported as NOT READY, not as a launchd success.
    assert not Path(payload["ProgramArguments"][0]).exists()


@pytest.mark.skipif(sys.platform != "darwin", reason="native macOS gate")
def test_real_worker_restarts_with_persistent_queue_and_bounded_lease_retries(
    tmp_path: Path,
) -> None:
    """Restart the real CLI process against the same SQLite WAL and outbox."""

    root = tmp_path / "runtime with spaces"
    database, queue = _database(root)
    historical = queue.create(TaskCreate(task_type="analysis", priority=0))
    recoverable = queue.create(
        TaskCreate(task_type="system.noop", priority=1, max_attempts=2)
    )
    exhausted = queue.create(
        TaskCreate(task_type="system.noop", priority=2, max_attempts=1)
    )
    for task_id in (recoverable.task_id, exhausted.task_id):
        leased = queue.lease_next(
            "dead-worker", lease_seconds=2, supported_task_types=("system.noop",)
        )
        assert leased is not None and leased.task_id == task_id
    database.execute(
        "UPDATE tasks SET lease_expires_at = ? WHERE lease_owner = ?",
        ((datetime.now(UTC) - timedelta(seconds=5)).isoformat(), "dead-worker"),
    )
    queued = queue.create(TaskCreate(task_type="system.noop", priority=3))
    first = _start(root, "p0-worker-first")
    try:
        _await_state(queue, {
            recoverable.task_id: TaskStatus.COMPLETED,
            exhausted.task_id: TaskStatus.FAILED,
            queued.task_id: TaskStatus.COMPLETED,
        }, first)
        assert queue.get(exhausted.task_id).attempt_count == 1
    finally:
        _stop(first)

    # Close and re-open SQLite to demonstrate on-disk queue and outbox durability.
    previous_events = int(database.scalar("SELECT COUNT(*) FROM event_outbox"))
    database.close()
    database, queue = _database(root)
    assert int(database.scalar("SELECT COUNT(*) FROM event_outbox")) >= previous_events
    assert queue.get(historical.task_id).status is TaskStatus.QUEUED
    assert queue.get(exhausted.task_id).status is TaskStatus.FAILED
    followup = queue.create(TaskCreate(task_type="system.noop", priority=4))
    second = _start(root, "p0-worker-restarted")
    try:
        _await_state(queue, {followup.task_id: TaskStatus.COMPLETED}, second)
    finally:
        _stop(second)
    assert queue.get(historical.task_id).status is TaskStatus.QUEUED
    assert queue.get(recoverable.task_id).attempt_count == 2
    assert queue.get(followup.task_id).attempt_count == 1
    database.close()


def test_resident_gpt_oss_health_preload_missing_and_connection_failure() -> None:
    """No Ollama downloads or paid inference; test real ResidentManager contract."""

    requests: list[tuple[str, dict[str, object]]] = []
    running = False

    def healthy(request: httpx.Request) -> httpx.Response:
        nonlocal running
        body = json.loads(request.content) if request.content else {}
        requests.append((request.url.path, body))
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "gpt-oss:20b"}]})
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": [
                {"name": "gpt-oss:20b"}] if running else []})
        if request.url.path == "/api/generate":
            assert body == {
                "model": "gpt-oss:20b", "prompt": "", "stream": False, "keep_alive": -1,
            }
            running = True
            return httpx.Response(200, json={"done": True})
        raise AssertionError(f"unexpected endpoint {request.url.path}")

    with httpx.Client(base_url="http://127.0.0.1:11434",
                      transport=httpx.MockTransport(healthy)) as client:
        result = ResidentManager(OllamaClient(client=client)).ensure_resident()
    assert result.status is ResidentStatus.RESIDENT
    assert [path for path, _ in requests].count("/api/generate") == 1

    with httpx.Client(base_url="http://127.0.0.1:11434",
                      transport=httpx.MockTransport(lambda req: httpx.Response(
                          200, json={"models": []}))) as client:
        assert ResidentManager(OllamaClient(client=client)).ensure_resident().status is (
            ResidentStatus.MODEL_MISSING
        )

    def unreachable(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated Ollama outage")

    with httpx.Client(base_url="http://127.0.0.1:11434",
                      transport=httpx.MockTransport(unreachable)) as client:
        assert ResidentManager(OllamaClient(client=client)).ensure_resident().status is (
            ResidentStatus.ERROR
        )


def test_windows_network_reconnect_replays_only_missing_event_sequences(
    tmp_path: Path,
) -> None:
    """Simulate Windows disconnect/reconnect without a second queue."""

    token = TOKEN
    app = create_app(AppSettings(
        paths=RuntimePaths.from_root(tmp_path / "core"), api_token=token
    ))
    auth = {"Authorization": f"Bearer {token}"}
    with TestClient(app) as client:
        assert client.get("/api/v1/health").json()["status"] == "ok"
        assert client.get("/api/v1/status").status_code == 401
        assert client.get("/api/v1/status", headers=auth).status_code == 200
        outbox = client.app.state.services.outbox
        before = outbox.list_after(0, limit=2000)
        cursor = max((event.sequence for event in before), default=0)
        outbox.append("p0.reconnect", {"step": 1})
        with client.websocket_connect(
            f"/api/v1/events?after_sequence={cursor}", headers=auth
        ) as socket:
            assert socket.receive_json()["topic"] == "connected"
            first = socket.receive_json()
            assert first["topic"] == "p0.reconnect"
            assert first["payload"] == {"step": 1}
            cursor = first["sequence"]
        # Transport disappears; Mac Core writes authoritative events while offline.
        outbox.append("p0.reconnect", {"step": 2})
        outbox.append("p0.reconnect", {"step": 3})
        with client.websocket_connect(
            f"/api/v1/events?after_sequence={cursor}", headers=auth
        ) as socket:
            assert socket.receive_json()["topic"] == "connected"
            second = socket.receive_json()
            third = socket.receive_json()
        assert [second["payload"]["step"], third["payload"]["step"]] == [2, 3]
        assert [second["sequence"], third["sequence"]] == sorted(
            {second["sequence"], third["sequence"]}
        )
        assert second["sequence"] > cursor
