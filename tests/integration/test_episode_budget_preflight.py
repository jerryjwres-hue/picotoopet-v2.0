"""CPU-only queue-budget regression; no GPU, LLM, model or cloud calls."""

from copy import deepcopy

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.domain.episode import Episode
from picotoopet_core.domain.episode_budget import (
    EpisodeBudgetPolicy,
    enforce_episode_budget,
    inspect_episode_budget,
)


def _episode():
    # 合法生产 Episode 合同，明确三镜头、4 秒、每镜两个候选。
    return {
        "episode_id": "E02",
        "title": "Maotai Dinner",
        "target_seconds": 12.0,
        "characters": ["maotai_master_v1"],
        "shots": [
            {
                "shot_id": f"S{i:02}",
                "seconds": 4.0,
                "beat": "Walk toward the dining table",
                "emotion": "curious",
                "camera": {"move": "tracking", "lens": 35.0, "speed": 1.0},
                "first_frame": {
                    "refs": ["maotai_master_v1"], "prompt": "Maintain approved identity",
                },
                "video": {
                    "prompt": "Follow the same dog toward dinner",
                    "negative": "flicker",
                    "seeds": [i * 100 + 1, i * 100 + 2],
                },
                "audio": {"vocal_from": "none", "foley": []},
                "transition_out": {"type": "cut", "offset_s": 0.0},
            }
            for i in range(1, 4)
        ],
        "edit": {"fps": 24.0, "size": [832, 480], "loudness_lufs": -14.0},
    }


@pytest.fixture
def api(tmp_path):
    settings = AppSettings(
        paths=RuntimePaths.from_root(tmp_path), api_token="b" * 32
    )
    with TestClient(
        create_app(settings),
        headers={"Authorization": "Bearer " + "b" * 32},
    ) as client:
        yield client


def _counts(api):
    db = api.app.state.services.database
    return (
        db.scalar("SELECT COUNT(*) FROM production_episodes"),
        db.scalar("SELECT COUNT(*) FROM tasks"),
        db.scalar("SELECT COUNT(*) FROM audit_events"),
    )


def test_budget_preview_reports_worst_case_without_writes(api):
    before = _counts(api)
    response = api.post("/api/v1/episodes/budget/preview", json=_episode())
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["allowed"] is True
    assert result["initial_video_takes"] == 6
    assert result["max_reserved_video_takes"] == 54
    assert result["initial_video_seconds"] == 24.0
    assert result["max_reserved_video_seconds"] == 216.0
    assert result["qc_redo_rounds"] == 2
    assert result["worker_attempts_per_generation"] == 3
    assert result["gpu_authorized"] is False
    assert result["read_only"] is True
    assert result["metric"] == "REQUESTED_VIDEO_OUTPUT_SECONDS_NOT_GPU_WALL_TIME"
    assert _counts(api) == before


@pytest.mark.parametrize(
    ("modify", "fragment"),
    [
        (lambda p: p["shots"][0]["video"].update(seeds=list(range(9))),
         "shots[0].video.seeds"),
        (lambda p: p["shots"][0]["video"].update(seeds=[7, 7]),
         "同一批不能重复种子"),
        (lambda p: p["shots"][0].update(seconds=400.0),
         "预计视频秒数超出预算"),
        (lambda p: p.update(shots=p["shots"] * 20),
         "首次候选总数上限"),
    ],
)
def test_budget_rejection_is_atomic_and_no_gpu_tasks(api, modify, fragment):
    payload = _episode()
    modify(payload)
    before = _counts(api)
    preview = api.post("/api/v1/episodes/budget/preview", json=payload)
    if len(payload["shots"]) > 3:
        # 重复 shot_id 是原 Episode 合同错误，应先由 Episode 校验拒绝。
        assert preview.status_code == 422
    else:
        assert preview.status_code == 200
        assert preview.json()["allowed"] is False
        assert any(fragment in reason for reason in preview.json()["errors"])
    create = api.post("/api/v1/episodes", json=payload)
    assert create.status_code == 422
    assert _counts(api) == before


def test_global_take_count_fails_independently_of_shot_ids(api):
    payload = _episode()
    for i in range(3):
        payload["shots"][i]["video"]["seeds"] = list(range(8 * i, 8 * (i + 1)))
    app = api.app
    from picotoopet_core.domain.episode_budget import EpisodeBudgetPolicy

    app.state.services.production.budget = EpisodeBudgetPolicy(
        max_takes_per_shot=8,
        max_takes_per_episode=20,
        max_reserved_video_seconds=720.0,
    )
    before = _counts(api)
    result = api.post("/api/v1/episodes/budget/preview", json=payload)
    assert result.status_code == 200
    assert "首次候选总数上限" in "".join(result.json()["errors"])
    assert api.post("/api/v1/episodes", json=payload).status_code == 422
    assert _counts(api) == before


def test_episode_create_is_idempotent_even_if_admin_later_reduces_budget(api):
    payload = _episode()
    created = api.post("/api/v1/episodes", json=payload)
    assert created.status_code == 201, created.text
    assert [task["max_attempts"] for task in created.json()["tasks"] if task["task_type"] == "gen.video"] == [3, 3, 3]
    first_counts = _counts(api)
    api.app.state.services.production.budget = EpisodeBudgetPolicy(
        max_takes_per_shot=1,
        max_takes_per_episode=1,
        max_reserved_video_seconds=12.0,
    )
    repeated = api.post("/api/v1/episodes", json=payload)
    assert repeated.status_code == 200
    assert repeated.json()["tasks"] == created.json()["tasks"]
    assert _counts(api) == first_counts
    modified = deepcopy(payload)
    modified["shots"][0]["video"]["seeds"] = [99]
    assert api.post("/api/v1/episodes", json=modified).status_code == 409
    assert _counts(api) == first_counts


def test_same_preview_for_json_and_yaml(api):
    value = _episode()
    x = api.post("/api/v1/episodes/budget/preview", json=value)
    y = api.post(
        "/api/v1/episodes/budget/preview",
        content=yaml.safe_dump(value),
        headers={"content-type": "application/yaml"},
    )
    assert x.status_code == y.status_code == 200
    assert x.json() == y.json()


def test_direct_service_create_cannot_skip_budget_check(api):
    p = _episode()
    p["shots"][0]["video"]["seeds"] = list(range(9))
    spec = Episode.model_validate(p)
    before = _counts(api)
    with pytest.raises(ValueError, match="超过单镜候选上限"):
        api.app.state.services.production.create(spec, "budget-test")
    assert _counts(api) == before


def test_config_limits_cannot_be_disabled_by_zero_or_unbounded_values(tmp_path):
    defaults = {"paths": RuntimePaths.from_root(tmp_path), "api_token": "c" * 32}
    with pytest.raises(ValidationError):
        AppSettings(**defaults, episode_max_takes_per_shot=0)
    with pytest.raises(ValidationError):
        AppSettings(**defaults, episode_max_takes_per_episode=100000)
    with pytest.raises(ValidationError):
        AppSettings(**defaults, episode_max_reserved_video_seconds=0)


def test_budget_is_not_claimed_as_real_gpu_active_time():
    result = inspect_episode_budget(
        Episode.model_validate(_episode()), EpisodeBudgetPolicy()
    )
    assert result["metric"] != "GPU_ACTIVE_SECONDS"
    assert result["gpu_authorized"] is False
    assert enforce_episode_budget(
        Episode.model_validate(_episode()), EpisodeBudgetPolicy()
    ) == result
