"""A complete Episode candidate is still unapproved and cannot create GPU jobs."""

from __future__ import annotations

import copy
import secrets

import pytest
from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.domain.episode import Episode
from picotoopet_core.domain.storypack import StoryPackV1, storypack_preview
from picotoopet_core.queue.production import _shot_jobs

_ENDPOINT = "/api/v1/studio/storypacks/episode-candidate/preview"


def _storypack() -> dict:
    return {
        "schema": "picotoo.storypack.v1",
        "episode_id": "MAOTAI03",
        "title": "Maotai walks home",
        "output_profile": "p0_landscape",
        "character_ref": "maotai_master_v1",
        "supporting_character_refs": ["owner_master_v1"],
        "scene_ref": "backyard_v1",
        "additional_scene_refs": ["home_door_v1"],
        "style_ref": "cartoon_style_v1",
        "story": {"goal": "Hear the dinner bell", "payoff": "Reach dinner"},
        "shots": [
            {
                "id": "S01", "action": "Play in backyard",
                "state_in": "Dog on grass", "state_out": "Dog holding ball",
                "because": "Establish the prop",
            },
            {
                "id": "S02", "action": "Hear owner's call",
                "state_in": "Dog holding ball", "state_out": "Dog looking at door",
                "because": "Introduce the call", "depends_on": ["S01"],
                "handoff": "continuous",
            },
            {
                "id": "S03", "action": "Arrive at dinner",
                "state_in": "Dog looking at door", "state_out": "Dog at doorstep",
                "because": "Resolve the story", "depends_on": ["S02"],
                "handoff": "scene_change", "scene_ref": "home_door_v1",
                "cast_refs": ["maotai_master_v1", "owner_master_v1"],
            },
        ],
    }


def _completion() -> dict:
    return {
        "edit": {"loudness_lufs": -14.0},
        "shots": [
            {
                "shot_id": shot_id,
                "emotion": "Curious" if index < 2 else "Happy",
                "camera": {"move": "locked-off", "lens": 35.0, "speed": 1.0},
                "first_frame": {
                    "refs": [f"untrusted-synthetic-frame-{index}.png"],
                    "prompt": f"Synthetic unapproved starting frame for {shot_id}",
                },
                "last_frame": None,
                "video": {
                    "prompt": f"Animate the stated action only for shot {shot_id}",
                    "negative": "flicker, identity drift",
                    "seeds": [100 + index, 200 + index],
                },
                "audio": {"vocal_from": "none", "foley": []},
                "transition_out": {"type": "cut", "offset_s": 0.0},
            }
            for index, shot_id in enumerate(["S01", "S02", "S03"])
        ],
    }


def _payload(pack: dict | None = None, completion: dict | None = None) -> dict:
    data = _storypack() if pack is None else pack
    return {
        "storypack": data,
        "storypack_sha256": storypack_preview(StoryPackV1.model_validate(data))["storypack_sha256"],
        "completion": _completion() if completion is None else completion,
    }


@pytest.fixture
def api(tmp_path):
    token = secrets.token_hex(24)
    app = create_app(AppSettings(paths=RuntimePaths.from_root(tmp_path), api_token=token))
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        yield client


def _no_production_writes(api: TestClient) -> None:
    database = api.app.state.services.database
    # 只允许 API 预览，永不创建任务、Episode、批准或审计记录。
    for table in ("tasks", "production_episodes", "approvals", "audit_events"):
        assert database.scalar(f"SELECT COUNT(*) FROM {table}") == 0, table


def test_three_shot_episode_candidate_valid_but_never_authorized(api):
    payload = _payload()
    first = api.post(_ENDPOINT, json=payload)
    assert first.status_code == 200, first.text
    result = first.json()
    assert result["episode_contract_valid"] is True
    assert result["status"] == "EPISODE_CONTRACT_VALID_UNTRUSTED"
    episode = Episode.model_validate(result["episode"])
    assert [s.shot_id for s in episode.shots] == ["S01", "S02", "S03"]
    assert [s.beat for s in episode.shots] == [s["action"] for s in payload["storypack"]["shots"]]
    assert all(s.seconds == 4.0 for s in episode.shots)
    assert episode.edit.fps == 24.0
    assert episode.edit.size == (832, 480)
    assert episode.target_seconds == 12.0
    assert episode.characters == []
    assert result["shot_context"][2]["cast_refs"] == [
        "maotai_master_v1", "owner_master_v1",
    ]
    assert result["shot_context"][2]["scene_ref"] == "home_door_v1"
    assert len(result["candidate_episode_sha256"]) == 64

    # 每镜场景因果已真正注入将由 Windows 生成的 Prompt，而不是仅在 Preview。
    for index, (shot, source) in enumerate(zip(
        episode.shots, payload["storypack"]["shots"], strict=True
    )):
        assert f"Starting situation: {source['state_in']}" in shot.video.prompt
        assert f"Visible action: {source['action']}" in shot.video.prompt
        assert f"Required ending situation: {source['state_out']}" in shot.video.prompt
        assert f"Story reason: {source['because']}" in shot.video.prompt
        assert f"Animate the stated action only for shot {shot.shot_id}" in shot.video.prompt
        assert shot.video.seeds == [100 + index, 200 + index]
        assert shot.video.negative == "flicker, identity drift"
        # 与已有 GPU Bridge 输入 JSON 对账，视频 Worker 实际读取该 prompt 字段。
        _, video_job, _ = _shot_jobs(episode, shot)
        assert video_job["jobs"][0]["prompt"] == shot.video.prompt

    assert "Opening story state to depict: Dog on grass" in episode.shots[0].first_frame.prompt
    assert "Opening story state to depict: Dog holding ball" in episode.shots[1].first_frame.prompt
    assert "Continue from the preceding shot's final visible state" in episode.shots[1].video.prompt
    assert "deliberate scene cut" in episode.shots[2].video.prompt
    # Scene change 不应把上一镜的后院状态硬写成新室内首帧画面。
    assert "Opening story state to depict:" not in episode.shots[2].first_frame.prompt
    assert result["references_trusted"] is False
    assert result["owner_approved"] is False
    assert result["can_queue"] is False
    assert result["can_generate"] is False
    assert result["can_publish"] is False
    assert result["budget_preview"]["allowed"] is True
    assert result["budget_preview"]["initial_video_takes"] == 6
    assert result["budget_preview"]["gpu_authorized"] is False

    repeat = api.post(_ENDPOINT, json=copy.deepcopy(payload))
    assert repeat.status_code == 200
    assert repeat.json() == result
    _no_production_writes(api)


@pytest.mark.parametrize("change", [
    "missing-shot", "shot-drift", "extra-key", "missing-camera",
    "wrong-seed", "duplicate-seed", "bad-first-frame", "override-edit",
    "override-shot", "claim-approved",
])
def test_invalid_or_untrusted_completion_never_creates_jobs(api, change):
    payload = _payload()
    if change == "missing-shot":
        payload["completion"]["shots"].pop()
    elif change == "shot-drift":
        payload["completion"]["shots"][1]["shot_id"] = "S99"
    elif change == "extra-key":
        payload["completion"]["shots"][0]["run_shell"] = "powershell.exe"
    elif change == "missing-camera":
        payload["completion"]["shots"][1].pop("camera")
    elif change == "wrong-seed":
        payload["completion"]["shots"][0]["video"]["seeds"] = [-1]
    elif change == "duplicate-seed":
        payload["completion"]["shots"][0]["video"]["seeds"] = [9, 9]
    elif change == "bad-first-frame":
        payload["completion"]["shots"][0]["first_frame"]["refs"] = []
    elif change == "override-edit":
        payload["completion"]["edit"]["fps"] = 60.0
    elif change == "override-shot":
        payload["completion"]["shots"][0]["seconds"] = 20.0
    elif change == "claim-approved":
        payload["completion"]["owner_approved"] = True
    response = api.post(_ENDPOINT, json=payload)
    assert response.status_code == 422, (change, response.text)
    _no_production_writes(api)


def test_narrative_plan_preserves_optional_last_frame_and_no_extra_gpu_tasks(api):
    payload = _payload()
    payload["completion"]["shots"][0]["last_frame"] = {
        "refs": ["synthetic-tail-still.png"],
        "prompt": "Tail holds the ball in frame",
    }
    response = api.post(_ENDPOINT, json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    first = result["episode"]["shots"][0]
    assert "Final story state to depict: Dog holding ball" in first["last_frame"]["prompt"]
    assert "Tail holds the ball in frame" in first["last_frame"]["prompt"]
    assert first["last_frame"]["refs"] == ["synthetic-tail-still.png"]
    assert first["video"]["seeds"] == [100, 200]
    assert result["owner_approved"] is False
    assert result["can_queue"] is False
    _no_production_writes(api)


def test_stale_storypack_source_digest_blocks_completion(api):
    payload = _payload()
    payload["storypack"]["shots"][0]["action"] = "Run instead"
    response = api.post(_ENDPOINT, json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "STORYPACK_SOURCE_SHA_STALE"
    _no_production_writes(api)


def test_storypack_completion_is_device_authenticated_and_bounded(api):
    payload = _payload()
    invalid = api.post(_ENDPOINT, json=payload, headers={"Authorization": "Bearer invalid"})
    assert invalid.status_code == 401
    oversized = api.post(
        _ENDPOINT,
        content=" " * (512 * 1024 + 1),
        headers={"Content-Type": "application/json"},
    )
    assert oversized.status_code == 413
    duplicate = (
        '{"storypack":{},"storypack":{},"storypack_sha256":"'
        + "a" * 64 + '","completion":{}}'
    )
    assert api.post(
        _ENDPOINT, content=duplicate,
        headers={"Content-Type": "application/json"},
    ).status_code == 422
    _no_production_writes(api)


def test_budget_overrun_is_visible_but_cannot_be_queued(api):
    payload = _payload()
    # 48 种子的模型允许格式输入，但单镜上限 8；这里只生成预算诊断。
    payload["completion"]["shots"][0]["video"]["seeds"] = list(range(18))
    response = api.post(_ENDPOINT, json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["episode_contract_valid"] is True
    assert result["budget_preview"]["allowed"] is False
    assert result["can_queue"] is False
    assert result["can_generate"] is False
    _no_production_writes(api)
