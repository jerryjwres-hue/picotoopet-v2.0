"""Goal Center 交付能力必须真实存在于 Mac Core/Worker 离线 wheel 与实机验收入口中。"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CORE_VERIFIER = ROOT / "scripts" / "mac" / "phase23" / "Test-MacCoreSliceBDelta.sh"
WORKER_VERIFIER = ROOT / "scripts" / "mac" / "phase23-worker" / "Test-MacWorkerSliceC.sh"
WORKER_BUILDER = ROOT / "scripts" / "mac" / "phase23-worker" / "Build-MacWorkerSliceC.sh"
LIVE_GOAL_CENTER_VERIFIER = (
    ROOT / "deploy" / "macos" / "phase23-worker" / "VERIFY_GOAL_CENTER_E2E.command"
)

REQUIRED_GOAL_CENTER_WHEEL_ENTRIES = (
    "picotoopet_core/api/routes/autonomous_goals.py",
    "picotoopet_core/api/routes/autonomous_intake.py",
    "picotoopet_core/autonomous/human_pipeline.py",
    "picotoopet_core/autonomous/legacy_import.py",
    "picotoopet_core/autonomous/browser_broker.py",
    "picotoopet_core/autonomous/goal_handoff_access.py",
    "picotoopet_core/autonomous/prompts/web_gpt_master_v1.txt",
)

REQUIRED_LIVE_TASK_TYPES = (
    "research.search",
    "autonomous.discovery.v1",
    "autonomous.goal_synthesis.v1",
    "autonomous.goal_handoff.v1",
)

REQUIRED_GOAL_CENTER_ROUTES = (
    "/api/v1/autonomous/goals/templates",
    "/api/v1/autonomous/goals",
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


def test_mac_worker_package_contains_separate_live_goal_center_readiness_verifier() -> None:
    assert LIVE_GOAL_CENTER_VERIFIER.is_file()

    verifier = _read(LIVE_GOAL_CENTER_VERIFIER)
    for task_type in REQUIRED_LIVE_TASK_TYPES:
        assert task_type in verifier
    for route in REQUIRED_GOAL_CENTER_ROUTES:
        assert route in verifier

    # 基础安装 VERIFY 可在离线 fixture 中通过；这个独立入口才负责严格判断
    # Research Gateway + 本地模型 + Goal handoff 是否已在用户实机同时就绪。
    assert "PHASE23_GOAL_CENTER_E2E_READY=PASS" in verifier
    assert "PICOTOO_FIXTURE_MODE" not in verifier

    builder = _read(WORKER_BUILDER)
    assert "VERIFY_GOAL_CENTER_E2E.command" in builder

    package_verifier = _read(WORKER_VERIFIER)
    assert "VERIFY_GOAL_CENTER_E2E.command" in package_verifier
