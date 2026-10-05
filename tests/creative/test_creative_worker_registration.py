from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_mac_worker_registers_creative_capability_only_with_local_model_health() -> None:
    cli = (ROOT / "src/picotoopet_core/cli.py").read_text(encoding="utf-8")
    execution = (ROOT / "src/picotoopet_core/creative/execution.py").read_text(
        encoding="utf-8"
    )
    assert "CreativeIntelligenceCoordinator" in cli
    assert 'CAPABILITY = "creative.intelligence.v1"' in execution
    assert 'TASK_TYPE = "creative.content_plan.v1"' in execution
    assert "business_adapter" in cli
    assert "creative_coordinator.handler" in cli
    assert (
        "runtime.handlers.pop(CreativeIntelligenceCoordinator.TASK_TYPE, None)"
        in cli
    )
    assert "capability=CreativeIntelligenceCoordinator.CAPABILITY" in cli


def test_creative_registration_does_not_start_or_download_model() -> None:
    cli = (ROOT / "src/picotoopet_core/cli.py").read_text(encoding="utf-8").lower()
    for forbidden in (
        "ollama pull",
        "ollama run",
        "brew install",
        "subprocess.run([\"ollama\"",
        "subprocess.popen([\"ollama\"",
    ):
        assert forbidden not in cli
