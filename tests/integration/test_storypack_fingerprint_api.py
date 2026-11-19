"""Read-only fingerprint preview has stable semantics across JSON and YAML."""

import secrets

import yaml
from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths


def _payload():
    return {
        "schema": "picotoo.storypack.v1",
        "episode_id": "E02",
        "title": "Maotai at home",
        "character_ref": "maotai_master_v1",
        "scene_ref": "backyard_v1",
        "style_ref": "movie_v1",
        "story": {"goal": "Play", "payoff": "Eat dinner"},
        "shots": [
            {
                "id": "S01", "action": "Play", "state_in": "Standing",
                "state_out": "Holding ball", "because": "Establish scene",
            },
            {
                "id": "S02", "action": "React", "state_in": "Holding ball",
                "state_out": "Looking at the door", "because": "Story progression",
                "depends_on": ["S01"], "handoff": "continuous",
            },
        ],
    }


def test_json_yaml_identical_fingerprints_with_no_task_side_effect(tmp_path):
    token = secrets.token_hex(24)
    app = create_app(AppSettings(paths=RuntimePaths.from_root(tmp_path), api_token=token))
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        url = "/api/v1/studio/storypacks/preview"
        first = client.post(url, json=_payload())
        second = client.post(
            url, content=yaml.safe_dump(_payload()), headers={"Content-Type": "text/yaml"}
        )
        assert first.status_code == second.status_code == 200
        a = first.json()["fingerprint_plan"]
        b = second.json()["fingerprint_plan"]
        assert a == b
        assert a["storypack_sha256"] == first.json()["storypack_sha256"]
        assert len(a["shots"]) == 2
        assert a["shots"][0]["input_sha256"] != a["shots"][1]["input_sha256"]
        assert all(shot["all_managed_bytes_verified"] is False for shot in a["shots"])
        assert a["can_reuse_for_generation"] is False
        assert a["can_queue"] is False
        assert first.json()["can_queue"] is False
        assert app.state.services.database.scalar("SELECT COUNT(*) FROM tasks") == 0
