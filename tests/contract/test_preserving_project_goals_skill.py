from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "preserving-project-goals" / "SKILL.md"


def test_skill_closes_goal_degradation_loopholes() -> None:
    text = SKILL.read_text(encoding="utf-8")

    assert "name: preserving-project-goals" in text
    assert "阻断可以改变进度状态，不能改变产品目标" in text
    assert "explicit user approval before implementation" in text.lower()
    for pressure_label in (
        "temporary",
        "equivalent",
        "fallback",
        "helper",
        "prototype",
        "local",
        "diagnostic",
    ):
        assert pressure_label in text.lower()
    for honest_status in ("BLOCKED", "UNVERIFIED", "DIAGNOSTIC"):
        assert honest_status in text
    assert "不得宣称完成" in text


def test_root_agent_instructions_require_the_skill_judgment() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "A blocker may change schedule or verification status" in agents
    assert "It may not change the approved product goal" in agents
    assert "explicit user approval" in agents.lower()
    assert "browser or localhost HTTP UI" in agents
    assert "separate Slice D Helper" in agents
