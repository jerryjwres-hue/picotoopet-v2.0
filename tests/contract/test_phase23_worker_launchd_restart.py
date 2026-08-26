"""Mac Worker LaunchAgent restart ordering regression contracts."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKER_LIB = ROOT / "deploy" / "macos" / "phase23-worker" / "worker-lib.sh"


def test_worker_restart_waits_until_launchd_finishes_bootout_before_bootstrap() -> None:
    """launchd bootout is asynchronous; same-label bootstrap must wait for removal."""

    source = WORKER_LIB.read_text(encoding="utf-8")

    assert "wait_for_worker_agent_unloaded()" in source
    assert 'launchctl print "gui/$UID/$(worker_label)"' in source

    stop_start = source.index("stop_worker_agent()")
    start_start = source.index("start_fixture_worker()")
    stop_body = source[stop_start:start_start]
    assert 'launchctl bootout "gui/$UID/$(worker_label)"' in stop_body
    assert "wait_for_worker_agent_unloaded" in stop_body
    assert stop_body.index("launchctl bootout") < stop_body.index(
        "wait_for_worker_agent_unloaded"
    )

    helper_start = source.index("wait_for_worker_agent_unloaded()")
    helper_end = source.index("stop_worker_agent()")
    helper_body = source[helper_start:helper_end]
    assert "for ((index = 0; index <" in helper_body
    assert "sleep 0.1" in helper_body
    assert "Worker LaunchAgent 未完成卸载" in helper_body
