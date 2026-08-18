"""Goal Center 交付能力必须真实存在于 Mac Core/Worker 离线 wheel 中。"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CORE_VERIFIER = ROOT / "scripts" / "mac" / "phase23" / "Test-MacCoreSliceBDelta.sh"
WORKER_VERIFIER = ROOT / "scripts" / "mac" / "phase23-worker" / "Test-MacWorkerSliceC.sh"

REQUIRED_GOAL_CENTER_WHEEL_ENTRIES = (
    "picotoopet_core/api/routes/autonomous_goals.py",
    "picotoopet_core/api/routes/autonomous_intake.py",
    "picotoopet_core/autonomous/human_pipeline.py",
    "picotoopet_core/autonomous/legacy_import.py",
    "picotoopet_core/autonomous/browser_broker.py",
    "picotoopet_core/autonomous/goal_handoff_access.py",
    "picotoopet_core/autonomous/prompts/web_gpt_master_v1.txt",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_mac_core_package_verifier_opens_project_wheel_and_requires_goal_center_runtime() -> None:
    verifier = _read(CORE_VERIFIER)

    assert "zipfile" in verifier
    assert "project_wheel" in verifier
    for entry in REQUIRED_GOAL_CENTER_WHEEL_ENTRIES:
        assert entry in verifier
    assert "PHASE23_MAC_CORE_GOAL_CENTER_CONTENT=PASS" in verifier


def test_mac_worker_package_verifier_requires_same_goal_center_runtime_and_prompt() -> None:
    verifier = _read(WORKER_VERIFIER)

    assert "zipfile" in verifier
    assert "project_wheel" in verifier
    for entry in REQUIRED_GOAL_CENTER_WHEEL_ENTRIES:
        assert entry in verifier
    assert "PHASE23_MAC_WORKER_GOAL_CENTER_CONTENT=PASS" in verifier
