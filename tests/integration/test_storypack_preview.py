"""StoryPack preview is an authenticated, deterministic dry run."""

import json
import secrets

import pytest
import yaml
from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths


@pytest.fixture
def api(tmp_path):
    token = secrets.token_hex(24)
    app = create_app(AppSettings(paths=RuntimePaths.from_root(tmp_path), api_token=token))
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        yield client


def storypack():
    return {
        "schema": "picotoo.storypack.v1",
        "episode_id": "E02",
        "title": "Maotai hears dinner",
        "output_profile": "p0_landscape",
        "character_ref": "maotai_master_v1",
        "scene_ref": "backyard_v1",
        "story": {"goal": "Maotai reacts to the owner's call", "payoff": "Maotai reaches dinner"},
        "shots": [
            {
                "id": "S01",
                "action": "Play with a ball",
                "state_in": "Maotai stands in the backyard",
                "state_out": "Maotai holds the ball",
                "because": "Establish the character and prop",
            },
            {
                "id": "S02",
                "action": "Hear owner's call",
                "state_in": "Maotai holds the ball",
                "state_out": "Maotai looks at the door",
                "because": "Motivate the next action",
                "depends_on": ["S01"],
                "handoff": "continuous",
            },
        ],
    }


def test_json_and_yaml_preview_do_not_create_tasks(api):
    route = "/api/v1/studio/storypacks/preview"
    pack = storypack()
    first = api.post(route, json=pack)
    assert first.status_code == 200
    data = first.json()
    assert data["validated"] is True
    assert data["can_queue"] is False
    assert data["output"]["planned_frames"] == 192
    assert data["output"]["width"] == 832
    assert data["required_gates"][0] == "ASSET_RIGHTS_AND_IDENTITY"
    assert len(data["storypack_sha256"]) == 64
    # 不论重复提交几次，预览都不会写入任务或触发 GPU。
    second = api.post(route, content=yaml.safe_dump(pack), headers={"Content-Type": "text/yaml"})
    assert second.status_code == 200
    assert second.json()["storypack_sha256"] == data["storypack_sha256"]
    assert api.app.state.services.database.scalar("SELECT COUNT(*) FROM tasks") == 0


@pytest.mark.parametrize("mutation", ["state", "duplicate", "extra", "path", "future"])
def test_invalid_storypacks_are_rejected(api, mutation):
    pack = storypack()
    if mutation == "state":
        pack["shots"][1]["state_in"] = "different state"
    elif mutation == "duplicate":
        pack["shots"][1]["id"] = "s01"
    elif mutation == "extra":
        pack["run_shell"] = "powershell.exe"
    elif mutation == "path":
        pack["scene_ref"] = "../../private"
    elif mutation == "future":
        pack["shots"][1]["depends_on"] = ["S99"]
    response = api.post("/api/v1/studio/storypacks/preview", json=pack)
    assert response.status_code == 422
    assert api.app.state.services.database.scalar("SELECT COUNT(*) FROM tasks") == 0


def test_unauthorized_and_oversized_preview_never_enqueues(api):
    route = "/api/v1/studio/storypacks/preview"
    assert api.post(route, json=storypack(), headers={"Authorization": "Bearer invalid"}).status_code == 401
    assert api.post(route, content="A" * (128 * 1024 + 1), headers={"Content-Type": "text/yaml"}).status_code == 413
    assert api.app.state.services.database.scalar("SELECT COUNT(*) FROM tasks") == 0


def test_portrait_preview_does_not_enable_rendering(api):
    pack = storypack()
    pack["output_profile"] = "design_portrait"
    response = api.post("/api/v1/studio/storypacks/preview", json=pack)
    assert response.status_code == 200
    assert response.json()["output"]["height"] == 832
    assert response.json()["can_queue"] is False
