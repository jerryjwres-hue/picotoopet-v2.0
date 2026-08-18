"""Autonomous work must run inside the existing Mac Worker loop, not a second daemon."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "src/picotoopet_core/cli.py"


def test_existing_worker_loop_hosts_autonomous_background_coordinator() -> None:
    source = CLI.read_text(encoding="utf-8")

    assert "from picotoopet_core.autonomous.background import AutonomousBackgroundCoordinator" in source
    assert "from picotoopet_core.autonomous.local_intelligence import" in source
    assert "LocalIntelligenceCoordinator" in source
    assert "build_ollama_local_intelligence_adapter" in source
    assert "autonomous_background = AutonomousBackgroundCoordinator(" in source
    # Reuse the existing loopback-model health probe; do not invent a second Ollama health system.
    assert "local_healthy = refresh_business_capability" in source
    assert "autonomous_background.refresh_local_intelligence(healthy=local_healthy)" in source
    assert "autonomous_background.tick_safely()" in source

    # The existing Worker still owns actual queue execution and the autonomous layer never starts a second loop.
    loop_body = source[source.index("while not stop_event.is_set():") :]
    assert loop_body.index("autonomous_background.tick_safely()") < loop_body.index("runtime.run_once()")
    assert "Thread(" not in source
    assert "Process(" not in source
    assert "autonomous-daemon" not in source


def test_worker_shutdown_removes_autonomous_local_analysis_capability() -> None:
    source = CLI.read_text(encoding="utf-8")

    assert "autonomous_background.refresh_local_intelligence(healthy=False)" in source
    assert "LocalIntelligenceCoordinator.TASK_TYPE" in source
