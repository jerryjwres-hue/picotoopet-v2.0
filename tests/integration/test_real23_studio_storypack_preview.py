"""#296: V3.1 Studio preview must leave real 2.3's production authority untouched."""

from __future__ import annotations

import copy
import json
import secrets

import pytest
from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.autonomous.goal_service import HumanGoalRequest
from picotoopet_core.creative.director import parse_goal_directives
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths

ROUTE = "/api/v1/studio/storypacks/preview"


@pytest.fixture
def studio(tmp_path):
    """以真实 2.3 Schema-24 初始化 Core；唯一差异是使用临时沙盒数据库。"""

    token = secrets.token_hex(24)
    app = create_app(AppSettings(paths=RuntimePaths.from_root(tmp_path), api_token=token))
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        yield client


def storypack() -> dict:
    """3×4 秒《茅台》测试结构只含语义输入，不构造可执行 GPU Plan。"""

    return {
        "schema": "picotoo.storypack.v1",
        "episode_id": "maotai_dinner_pilot",
        "title": "Maotai Dinner",
        "output_profile": "p0_landscape",
        "character_ref": "maotai_master_v1",
        "scene_ref": "dinner_room_v1",
        "style_ref": "cute_3d_style_v1",
        "story": {
            "goal": "Maotai wants dinner",
            "payoff": "Maotai reaches his bowl",
        },
        "shots": [
            {
                "id": "S01",
                "action": "Maotai sees his bowl",
                "state_in": "Maotai by the door",
                "state_out": "Maotai by the bowl",
                "because": "He smells dinner",
            },
            {
                "id": "S02",
                "action": "Maotai looks at the bowl",
                "state_in": "Maotai by the bowl",
                "state_out": "Maotai is sitting",
                "because": "He is curious",
                "depends_on": ["S01"],
                "handoff": "continuous",
            },
            {
                "id": "S03",
                "action": "Maotai enjoys dinner",
                "state_in": "Maotai is sitting",
                "state_out": "Maotai is happy",
                "because": "His bowl is ready",
                "depends_on": ["S02"],
                "handoff": "continuous",
            },
        ],
    }


def _counts(client: TestClient) -> tuple[int, int, int]:
    """原有任务、审批、生产 Job 的计数构成只读性不变量。"""

    db = client.app.state.services.database
    return tuple(
        int(db.scalar(f"SELECT COUNT(*) FROM {table}") or 0)
        for table in ("tasks", "approvals", "production_jobs")
    )


def test_three_shot_preview_is_deterministic_and_never_enqueues(studio):
    before = _counts(studio)
    first = studio.post(ROUTE, json=storypack())
    assert first.status_code == 200, first.text
    data = first.json()
    assert data["validated"] is True
    assert data["shot_count"] == 3
    assert data["output"]["width"] == 832
    assert data["output"]["height"] == 480
    assert data["output"]["fps"] == 24
    # Use the canonical Wan 4n+1 frame count, not simplistic 4 × 24 = 96.
    assert data["output"]["frames_per_shot"] == 97
    assert data["output"]["planned_frames"] == 291
    assert data["output"]["planned_duration_s"] == 12
    assert data["can_queue"] is False
    assert data["production_compilation"]["executable"] is False
    intake = data["canonical_goal_intake"]
    assert intake["ready_for_user_submission"] is True
    assert intake["requires_explicit_user_action"] is True
    assert intake["storypack_sha256"] == data["storypack_sha256"]
    assert intake["goal_type"] == "video.creative"
    assert intake["depth"] == "standard"
    assert intake["local_video_preferred"] is True
    assert all(intake[key] is False for key in (
        "source_evidence_verified", "creative_package_approved",
        "production_plan_executable", "owner_approved", "gpu_post_authorized",
    ))
    # 现有 2.3 Goal 契约能真实接受提案；预览本身仍没有提交 Goal。
    _ = HumanGoalRequest.model_validate({
        "goal_type": intake["goal_type"],
        "depth": intake["depth"],
        "objective": intake["objective"],
        "local_video_preferred": intake["local_video_preferred"],
    })
    directives = parse_goal_directives(intake["objective"])
    assert directives.shot_count == 3
    assert directives.shot_seconds == 4
    assert directives.pet_only is True
    assert data["production_compilation"]["reason"] == "CANONICAL_23_PRODUCTION_BRIDGE_NOT_IMPLEMENTED"
    assert data["core23_compatibility"]["gpu_post_authorized"] is False
    assert data["owner_review_subject"]["owner_approved"] is False
    assert data["owner_review_subject"]["status"] == "BLOCKED_INCOMPLETE_EVIDENCE"
    assert data["fingerprint_plan"]["can_queue"] is False
    assert all(not item["usable_for_generation"] for item in data["asset_record_checks"])
    assert first.headers["cache-control"] == "no-store, private"

    # 同一输入不产生新任务、Lease、审批或实机 Comfy POST。
    second = studio.post(ROUTE, json=storypack())
    assert second.status_code == 200
    assert second.json()["storypack_sha256"] == data["storypack_sha256"]
    assert second.json()["fingerprint_plan"] == data["fingerprint_plan"]
    assert _counts(studio) == before


@pytest.mark.parametrize("reason", ["state", "duplicate_shot", "path", "unknown_dep", "extra_key"])
def test_invalid_storypack_cannot_escape_canonical_core(studio, reason):
    pack = copy.deepcopy(storypack())
    if reason == "state":
        pack["shots"][1]["state_in"] = "wrong continuity"
    elif reason == "duplicate_shot":
        pack["shots"][1]["id"] = "s01"
    elif reason == "path":
        pack["scene_ref"] = "../../private"
    elif reason == "unknown_dep":
        pack["shots"][1]["depends_on"] = ["S99"]
    else:
        pack["execute_shell"] = "powershell.exe"

    before = _counts(studio)
    response = studio.post(ROUTE, json=pack)
    assert response.status_code == 422
    assert _counts(studio) == before


def test_untrusted_request_never_reads_studio_preview(studio):
    before = _counts(studio)
    denied = studio.post(
        ROUTE, json=storypack(), headers={"Authorization": "Bearer unauthorized"}
    )
    assert denied.status_code == 401
    assert _counts(studio) == before


def test_duplicate_keys_and_nonfinite_json_fail_closed(studio):
    before = _counts(studio)
    for body in (
        b'{"schema":"picotoo.storypack.v1","schema":"picotoo.storypack.v1"}',
        json.dumps(storypack()).replace('"shots":', '"shots": NaN, "shots":').encode(),
    ):
        response = studio.post(
            ROUTE, content=body, headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 422
    assert _counts(studio) == before


def test_oversize_yaml_and_unsupported_content_are_denied(studio):
    before = _counts(studio)
    oversized = studio.post(
        ROUTE,
        content=b"x" * (128 * 1024 + 1),
        headers={"Content-Type": "application/json"},
    )
    assert oversized.status_code == 413
    yaml_attempt = studio.post(
        ROUTE,
        content="schema: picotoo.storypack.v1",
        headers={"Content-Type": "application/yaml"},
    )
    assert yaml_attempt.status_code == 415
    assert _counts(studio) == before


def test_changes_are_scoped_to_dependent_shots(studio):
    base = studio.post(ROUTE, json=storypack()).json()
    modified = storypack()
    modified["shots"][0]["action"] = "Maotai follows the food bowl"
    newer = studio.post(ROUTE, json=modified).json()
    assert newer["storypack_sha256"] != base["storypack_sha256"]
    old_keys = [shot["input_sha256"] for shot in base["fingerprint_plan"]["shots"]]
    new_keys = [shot["input_sha256"] for shot in newer["fingerprint_plan"]["shots"]]
    assert all(old != new for old, new in zip(old_keys, new_keys, strict=True))
    assert newer["can_queue"] is False


def test_goal_intake_blocks_oversize_and_non_p0_without_writing(studio):
    """不截断故事，也不让不合规格的草稿静默变成 Goal。"""

    before = _counts(studio)
    too_long = storypack()
    for shot in too_long["shots"]:
        shot["action"] = shot["action"] + (" 长动作" * 210)
    long_response = studio.post(ROUTE, json=too_long)
    assert long_response.status_code == 200
    long_intake = long_response.json()["canonical_goal_intake"]
    assert long_intake["ready_for_user_submission"] is False
    assert long_intake["objective"] is None
    assert "GOAL_OBJECTIVE_OVER_2000_CHARS" in long_intake["blocking_reasons"]
    assert long_response.json()["production_compilation"]["executable"] is False

    two_shots = storypack()
    two_shots["shots"] = two_shots["shots"][:2]
    two_response = studio.post(ROUTE, json=two_shots)
    assert two_response.status_code == 200
    two_intake = two_response.json()["canonical_goal_intake"]
    assert two_intake["ready_for_user_submission"] is False
    assert "P0_REQUIRES_EXACTLY_THREE_SHOTS" in two_intake["blocking_reasons"]
    assert two_intake["objective"] is None
    assert _counts(studio) == before
