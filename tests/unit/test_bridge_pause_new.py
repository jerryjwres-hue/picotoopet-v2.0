"""Local pause/new-lease safety checks; CPU only, no Core/GPU required."""

import json
import sys
import time
from pathlib import Path

import pytest
from requests import Response

from scripts.windows.executor_bridge import (
    Bridge,
    BridgeConfig,
    _pause_marker,
    atomic_json,
    main,
    manage_new_task_pause,
)


class StubSession:
    """Record HTTP requests without contacting Mac Core or ComfyUI."""

    def __init__(self):
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url))
        response = Response()
        response.status_code = 204 if url.endswith("/executors/lease") else 200
        response.url = url
        response._content = b"{}"
        return response


@pytest.fixture
def bridge(tmp_path):
    # 独立假项目目录，只测试本机标记及已有 Journal 的回收路径。
    root = tmp_path / "project"
    root.mkdir()
    config = BridgeConfig("http://127.0.0.1:8765", "test-bridge", root)
    session = StubSession()
    return Bridge(config, session), session


def _running_task():
    return {
        "task_id": "test_task_01",
        "task_type": "gen.video",
        "attempt_count": 1,
        "timeout_seconds": 60,
        "payload": {
            "runner": "run_ltx_flf.py",
            "jobs": {"jobs": []},
            "args": [],
        },
    }


def test_pause_blocks_new_lease_but_does_not_contact_core(bridge):
    worker, session = bridge
    status = manage_new_task_pause(worker.config, "pause")
    assert status["new_task_leases_paused"] is True
    assert status["scope"] == "THIS_WINDOWS_BRIDGE_ONLY"
    assert status["global_gpu_hold_unchanged"] is True
    worker.step()
    assert session.calls == []
    assert not worker.journal.exists()
    assert manage_new_task_pause(worker.config, "status") == status
    assert manage_new_task_pause(worker.config, "resume")["new_task_leases_paused"] is False
    worker.step()
    assert len(session.calls) == 1
    assert session.calls[0][1].endswith("/executors/lease")


def test_pause_mid_lease_preserves_heartbeat_and_unsubmitted_journal(bridge):
    worker, session = bridge
    worker._new_state(_running_task())
    manage_new_task_pause(worker.config, "pause")
    worker.step()
    assert worker.journal.exists()
    assert not list((worker.queue / "inbox").glob("*.json"))
    assert not list((worker.queue / "running").glob("*.json"))
    assert any(url.endswith("/heartbeat") for _, url in session.calls)
    assert not any(url.endswith("/executors/lease") for _, url in session.calls)


def test_pause_does_not_abandon_submitted_worker_receipt(bridge):
    worker, session = bridge
    state = worker._new_state(_running_task())
    state["submitted"] = True
    state["submitted_at"] = time.time()
    atomic_json(worker.journal, state)
    receipt = worker.queue / "failed" / f"{state['stem']}.result.json"
    receipt.write_text(
        json.dumps({"ok": False, "error": "synthetic failure", "retryable": False}),
        encoding="utf-8",
    )
    manage_new_task_pause(worker.config, "pause")
    worker.step()
    assert not worker.journal.exists()
    assert any(url.endswith("/fail") for _, url in session.calls)
    assert not any(url.endswith("/executors/lease") for _, url in session.calls)
    assert _pause_marker(worker.config).exists()


def test_pause_survives_worker_reconstruction(bridge):
    worker, session = bridge
    manage_new_task_pause(worker.config, "pause")
    restarted = Bridge(worker.config, session)
    restarted.step()
    assert session.calls == []
    assert restarted.pause_marker.is_file()


def test_pause_marker_symlink_never_redirects_local_control(bridge, tmp_path):
    worker, session = bridge
    marker = _pause_marker(worker.config)
    outside = tmp_path / "outside.txt"
    outside.write_text("KEEP", encoding="utf-8")
    try:
        marker.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError, match="符号链接"):
        manage_new_task_pause(worker.config, "resume")
    assert outside.read_text(encoding="utf-8") == "KEEP"
    worker.step()
    assert session.calls == []


def test_cli_pause_and_resume_need_no_device_token(bridge, monkeypatch, capsys):
    worker, session = bridge
    root = worker.config.root
    config = root / "local-bridge.toml"
    config.write_text(
        'mac_core_url = "http://127.0.0.1:8765"\n'
        'worker_id = "test-bridge"\n'
        f'project_root = "{root.as_posix()}"\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("PICOTOO_EXECUTOR_TOKEN", raising=False)
    for command, expected in (
        ("--pause-new", True), ("--pause-status", True), ("--resume-new", False)
    ):
        monkeypatch.setattr(sys, "argv", ["executor_bridge", str(config), command])
        assert main() is None
        status = json.loads(capsys.readouterr().out)
        assert status["new_task_leases_paused"] is expected
        assert status["global_gpu_hold_unchanged"] is True
    assert session.calls == []
