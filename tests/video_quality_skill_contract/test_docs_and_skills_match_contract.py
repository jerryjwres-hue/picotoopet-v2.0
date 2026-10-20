"""Docs and Skills must not drift from the executable contract, or overclaim visual quality."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from video_bible_reference import (
    ADAPTERS,
    CAMERA_PHRASE,
    CameraMovement,
    Handoff,
    NegativeConcept,
    RiskFlag,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = (ROOT / "docs/p0_video_quality/video_bible_contract_v1.md").read_text(encoding="utf-8")
PROTOCOL = (ROOT / "docs/p0_video_quality/model_prompt_ab_protocol.md").read_text(encoding="utf-8")
SOURCE = (Path(__file__).parent / "video_bible_reference.py").read_text(encoding="utf-8")
SKILLS = {
    name: (ROOT / f".agents/skills/picotoopet-{name}/SKILL.md").read_text(encoding="utf-8")
    for name in ("story-director", "shot-prompt-engineer", "visual-critic")
}
GOLDEN_IDS = sorted(p.stem for p in (Path(__file__).parent / "golden").glob("*.json"))


def _finding_codes() -> list[str]:
    return sorted(set(re.findall(r'add\(\s*"([A-Z_]+)"', SOURCE)))


def test_every_lint_code_is_documented_with_its_severity() -> None:
    codes = _finding_codes()
    assert len(codes) >= 15
    for code in codes:
        assert f"`{code}`" in CONTRACT, f"{code} missing from the contract table"


@pytest.mark.parametrize(
    "value",
    [m.value for m in CameraMovement]
    + [m.value for m in RiskFlag]
    + [m.value for m in Handoff]
    + [m.value for m in NegativeConcept],
)
def test_every_enum_member_is_documented(value: str) -> None:
    assert value in CONTRACT


def test_camera_phrases_cover_every_movement() -> None:
    assert set(CAMERA_PHRASE) == set(CameraMovement)


@pytest.mark.parametrize("fixture_id", GOLDEN_IDS)
def test_every_golden_fixture_is_listed(fixture_id: str) -> None:
    assert fixture_id in CONTRACT


@pytest.mark.parametrize("adapter_id", sorted(ADAPTERS))
def test_every_adapter_is_listed_in_the_protocol(adapter_id: str) -> None:
    assert adapter_id in PROTOCOL


def test_contract_states_the_visual_qa_boundary_and_the_attempt_ceiling() -> None:
    assert "visual_qa" in CONTRACT and "UNVERIFIED" in CONTRACT
    assert "MAX_COMFY_ATTEMPTS = 2" in CONTRACT
    assert "output_sha256" in CONTRACT


def test_protocol_marks_unconfirmed_upstream_facts_instead_of_guessing() -> None:
    assert "UNVERIFIED" in PROTOCOL
    for adapter_id, adapter in ADAPTERS.items():
        if adapter.status.value == "EVALUATION_ONLY":
            assert adapter_id in PROTOCOL


@pytest.mark.parametrize("name", sorted(SKILLS))
def test_skills_are_instruction_only_and_never_grant_execution(name: str) -> None:
    text = SKILLS[name]
    assert text.startswith("---\nname: picotoopet-")
    lowered = text.lower()
    for forbidden in ("http://", "https://", "powershell", "cmd.exe"):
        assert forbidden not in lowered
    assert "UNVERIFIED" in text


def test_visual_critic_requires_real_frames_and_cannot_accept_without_them() -> None:
    text = SKILLS["visual-critic"]
    assert "output_sha256" in text and "VISUAL_QA=UNVERIFIED" in text
    assert "never `ACCEPT`" in text
    assert "MAX_COMFY_ATTEMPTS = 2" in text


def test_prompt_engineer_forbids_hype_terms_and_executor_output() -> None:
    text = SKILLS["shot-prompt-engineer"]
    assert "Do **not** use hype terms" in text
    assert "never emit a negative prompt, workflow JSON or HTTP call" in text
