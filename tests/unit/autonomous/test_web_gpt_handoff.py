"""Web GPT receives a compact evidence-grounded production package, not raw crawl noise."""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from picotoopet_core.autonomous.handoff import HandoffSafetyError, WebGptHandoffBuilder
from picotoopet_core.autonomous.models import (
    GoalOrigin,
    GoalRecord,
    GoalStatus,
    PriorityClass,
)
from picotoopet_core.config.paths import RuntimePaths


NOW = datetime(2026, 8, 18, 4, 0, tzinfo=UTC)
REQUIRED = {
    "00_README_直接拖给GPT.md",
    "01_GOAL.json",
    "02_EXECUTIVE_BRIEF.md",
    "03_VALIDATED_FACTS.json",
    "04_EVIDENCE.md",
    "05_SOURCE_MANIFEST.json",
    "06_AUDIENCE_INSIGHTS.md",
    "07_CONTENT_PATTERNS.md",
    "08_OPPORTUNITIES.md",
    "09_CREATIVE_BRIEF.md",
    "10_CONSTRAINTS.md",
    "WEB_GPT_MASTER_PROMPT.txt",
    "HANDOFF_MANIFEST.json",
}


def _goal() -> GoalRecord:
    return GoalRecord(
        goal_id="goal-content-001",
        origin=GoalOrigin.HUMAN,
        intent_type="content.video_research",
        priority_class=PriorityClass.P1,
        objective="基于真实高互动内容模式，为宠物产品生成 AI 视频研究交接包。",
        constraints={"market": "US", "platforms": ["youtube", "reddit"]},
        budget_class="local-first",
        pinned=True,
        status=GoalStatus.COMPLETED,
        idempotency_key="goal-content-001",
        created_at=NOW,
        updated_at=NOW,
    )


def _builder(tmp_path: Path) -> WebGptHandoffBuilder:
    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.ensure()
    return WebGptHandoffBuilder(paths, clock=lambda: NOW)


def _inputs() -> dict[str, object]:
    return {
        "analysis": {
            "executive_summary": "高互动样本反复出现宠物拟人上班场景与前三秒冲突。",
            "validated_facts": [
                {"fact": "主题在两个独立来源出现", "evidence_ids": ["ev-001", "ev-002"]}
            ],
            "audience_insights": ["观众对宠物拟人化和生活共鸣反应更强"],
            "content_patterns": ["前三秒冲突 -> 拟人行为 -> 反转"],
            "opportunities": ["把桌宠/办公情境和真实产品卖点结合"],
        },
        "evidence": [
            {"evidence_id": "ev-001", "source_id": "src-001", "text": "高互动样本 A 的结构化证据"},
            {"evidence_id": "ev-002", "source_id": "src-002", "text": "高互动样本 B 的结构化证据"},
        ],
        "sources": [
            {"source_id": "src-001", "url": "https://example.com/a", "captured_at": NOW.isoformat()},
            {"source_id": "src-002", "url": "https://example.com/b", "captured_at": NOW.isoformat()},
        ],
        "creative_brief": {
            "objective": "生成 30 秒竖屏 AI 视频方向",
            "must_keep": ["产品外观一致", "事实和创意分开"],
        },
    }


def test_builder_writes_fixed_prompt_traceable_manifest_and_required_files(tmp_path: Path) -> None:
    builder = _builder(tmp_path)
    package = builder.build(goal=_goal(), **_inputs())

    assert package.is_file()
    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        assert REQUIRED <= names
        manifest = json.loads(archive.read("HANDOFF_MANIFEST.json"))
        prompt = archive.read("WEB_GPT_MASTER_PROMPT.txt").decode("utf-8")
        evidence_text = archive.read("04_EVIDENCE.md").decode("utf-8")
        sources = json.loads(archive.read("05_SOURCE_MANIFEST.json"))

        assert manifest["prompt_version"] == "web-gpt-master-v1.0"
        assert manifest["goal_id"] == "goal-content-001"
        assert manifest["evidence_ids"] == ["ev-001", "ev-002"]
        assert manifest["source_ids"] == ["src-001", "src-002"]
        assert "已验证事实" in prompt
        assert "创意" in prompt
        assert "ev-001" in evidence_text and "src-001" in evidence_text
        assert sources["sources"][0]["source_id"] == "src-001"

        for name, expected_sha in manifest["file_sha256"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == expected_sha


def test_same_inputs_and_clock_produce_same_zip_bytes(tmp_path: Path) -> None:
    builder = _builder(tmp_path)
    first = builder.build(goal=_goal(), **_inputs())
    first_bytes = first.read_bytes()
    second = builder.build(goal=_goal(), **_inputs())
    assert second.read_bytes() == first_bytes


def test_builder_rejects_local_paths_credentials_and_broken_evidence_links(tmp_path: Path) -> None:
    builder = _builder(tmp_path)
    safe = _inputs()

    with pytest.raises(HandoffSafetyError, match="local path"):
        builder.build(
            goal=_goal(),
            analysis={"executive_summary": "x", "validated_facts": []},
            evidence=[{"evidence_id": "ev-path", "source_id": "src-path", "text": "x", "local_path": "/Users/me/raw.html"}],
            sources=[{"source_id": "src-path", "url": "https://example.com"}],
            creative_brief={},
        )

    with pytest.raises(HandoffSafetyError, match="credential"):
        builder.build(
            goal=_goal(),
            analysis={"executive_summary": "x", "validated_facts": []},
            evidence=[],
            sources=[],
            creative_brief={"api_token": "secret-value"},
        )

    with pytest.raises(HandoffSafetyError, match="unknown source_id"):
        broken = dict(safe)
        broken["evidence"] = [
            {"evidence_id": "ev-broken", "source_id": "src-missing", "text": "x"}
        ]
        builder.build(goal=_goal(), **broken)
