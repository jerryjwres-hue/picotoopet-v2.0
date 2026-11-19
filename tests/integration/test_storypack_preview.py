"""StoryPack preview is an authenticated, deterministic dry run."""

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
    denied = api.post(route, json=storypack(), headers={"Authorization": "Bearer invalid"})
    assert denied.status_code == 401
    oversized = api.post(
        route, content="A" * (128 * 1024 + 1), headers={"Content-Type": "text/yaml"}
    )
    assert oversized.status_code == 413
    assert api.app.state.services.database.scalar("SELECT COUNT(*) FROM tasks") == 0


def test_multi_scene_and_cast_are_declared_and_previewed(api):
    pack = storypack()
    pack["style_ref"] = "picotoo_cinematic_v1"
    pack["supporting_character_refs"] = ["owner_master_v1"]
    pack["additional_scene_refs"] = ["home_door_v1"]
    shot = pack["shots"][1]
    shot["scene_ref"] = "home_door_v1"
    shot["cast_refs"] = ["maotai_master_v1", "owner_master_v1"]
    shot["handoff"] = "scene_change"
    response = api.post("/api/v1/studio/storypacks/preview", json=pack)
    assert response.status_code == 200
    data = response.json()
    assert data["shots"][1]["scene_ref"] == "home_door_v1"
    assert data["shots"][1]["cast_refs"] == ["maotai_master_v1", "owner_master_v1"]
    assert data["missing_design_locks"] == []
    assert set(data["unresolved_asset_refs"]) == {
        "maotai_master_v1", "owner_master_v1",
        "backyard_v1", "home_door_v1", "picotoo_cinematic_v1",
    }
    assert data["can_queue"] is False


@pytest.mark.parametrize("problem", ["unknown_scene", "unknown_cast", "scene_drift", "duplicate_cast"])
def test_storypack_rejects_undeclared_assets_or_continuity_drift(api, problem):
    pack = storypack()
    if problem == "unknown_scene":
        pack["shots"][1]["scene_ref"] = "kitchen_unapproved_v1"
    elif problem == "unknown_cast":
        pack["shots"][1]["cast_refs"] = ["unknown_actor_v1"]
    elif problem == "scene_drift":
        pack["additional_scene_refs"] = ["home_door_v1"]
        pack["shots"][1]["scene_ref"] = "home_door_v1"
    else:
        pack["supporting_character_refs"] = ["maotai_master_v1"]
    response = api.post("/api/v1/studio/storypacks/preview", json=pack)
    assert response.status_code == 422
    assert api.app.state.services.database.scalar("SELECT COUNT(*) FROM tasks") == 0


def test_missing_style_is_visible_as_unfinished_lock(api):
    response = api.post("/api/v1/studio/storypacks/preview", json=storypack())
    assert response.status_code == 200
    assert response.json()["missing_design_locks"] == ["style_ref"]
    assert response.json()["can_queue"] is False


def test_episode_compiler_uses_existing_contract_and_keeps_draft_nonexecutable(api):
    from pydantic import ValidationError

    from picotoopet_core.domain.episode import Episode

    route = "/api/v1/studio/storypacks/preview"
    first = api.post(route, json=storypack())
    assert first.status_code == 200
    preview = first.json()
    compilation = preview["production_compilation"]
    assert compilation["source_storypack_sha256"] == preview["storypack_sha256"]
    assert compilation["episode_schema"] == "picotoopet_core.domain.episode.Episode"
    assert compilation["episode_contract_valid"] is False
    assert compilation["executable"] is False
    assert compilation["can_queue"] is False
    assert compilation["can_generate"] is False
    assert compilation["can_publish"] is False
    assert compilation["episode_draft"]["shots"][0]["camera"] is None
    assert compilation["episode_draft"]["shots"][0]["video"] is None
    assert compilation["shared_asset_refs"]["verified"] is False
    assert compilation["shot_context"][1]["state_in"] == "Maotai holds the ball"
    assert "OWNER_PRINCIPAL_VERIFIED" in compilation["missing_trust_gates"]
    with pytest.raises(ValidationError):
        Episode.model_validate(compilation["episode_draft"])
    # 仅复核契约，既不产生数据库记录，也不能绕过 GPU HOLD。
    assert api.app.state.services.database.scalar("SELECT COUNT(*) FROM tasks") == 0


def test_compiler_draft_is_repeatable_and_uses_declared_scene_assets(api):
    pack = storypack()
    pack["additional_scene_refs"] = ["home_door_v1"]
    pack["style_ref"] = "cinematic_v1"
    pack["shots"][1]["scene_ref"] = "home_door_v1"
    pack["shots"][1]["handoff"] = "scene_change"
    first = api.post("/api/v1/studio/storypacks/preview", json=pack)
    second = api.post("/api/v1/studio/storypacks/preview", json=pack)
    assert first.status_code == second.status_code == 200
    a = first.json()["production_compilation"]
    b = second.json()["production_compilation"]
    assert a == b
    assert a["shot_context"][1]["scene_ref"] == "home_door_v1"
    assert a["shared_asset_refs"]["scenes"] == ["backyard_v1", "home_door_v1"]
    assert a["shared_asset_refs"]["style"] == "cinematic_v1"


def test_duplicate_json_or_yaml_keys_fail_closed_before_digest(api):
    import json

    pack = storypack()
    route = "/api/v1/studio/storypacks/preview"
    raw_json = json.dumps(pack, ensure_ascii=False).replace(
        '"episode_id": "E02"', '"episode_id": "E02", "episode_id": "E03"',
    )
    assert api.post(
        route, content=raw_json, headers={"Content-Type": "application/json"}
    ).status_code == 422

    raw_yaml = yaml.safe_dump(pack, allow_unicode=True) + "episode_id: E03\n"
    assert api.post(
        route, content=raw_yaml, headers={"Content-Type": "text/yaml"}
    ).status_code == 422
    assert api.app.state.services.database.scalar("SELECT COUNT(*) FROM tasks") == 0


def test_registry_missing_assets_never_receive_owner_approval(api):
    response = api.post("/api/v1/studio/storypacks/preview", json=storypack())
    assert response.status_code == 200
    checks = response.json()["asset_record_checks"]
    assert [item["ref"] for item in checks] == ["maotai_master_v1", "backyard_v1"]
    assert all(item["registry_record_status"] == "RECORD_NOT_FOUND" for item in checks)
    assert all(item["owner_approval_verified"] is False for item in checks)
    assert all(item["usable_for_generation"] is False for item in checks)
    assert response.json()["can_queue"] is False


def test_existing_artifact_record_is_not_authorized_asset(api):
    database = api.app.state.services.database
    database.execute(
        """INSERT INTO projects
           (project_id, title, project_type, source_app, classification,
            status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("fixture-project", "Fixture", "pet", "test", "internal", "Active",
         "2026-11-19T00:00:00Z", "2026-11-19T00:00:00Z"),
    )
    database.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, artifact_type, classification,
            sha256, is_original, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("maotai_master_v1", "fixture-project", "image", "internal",
         "a" * 64, 1, "2026-11-19T00:00:00Z"),
    )
    before = database.scalar("SELECT COUNT(*) FROM artifacts")
    response = api.post("/api/v1/studio/storypacks/preview", json=storypack())
    assert response.status_code == 200
    checks = {item["ref"]: item for item in response.json()["asset_record_checks"]}
    maotai = checks["maotai_master_v1"]
    assert maotai["registry_record_status"] == "RECORDED_UNAPPROVED"
    assert maotai["sha256_recorded"] is True
    assert maotai["original_flag_recorded"] is True
    assert maotai["content_integrity_verified"] is False
    assert maotai["owner_approval_verified"] is False
    assert maotai["physical_file_verified"] is False
    assert maotai["usable_for_generation"] is False
    assert checks["backyard_v1"]["registry_record_status"] == "RECORD_NOT_FOUND"
    assert response.json()["can_queue"] is False
    assert database.scalar("SELECT COUNT(*) FROM artifacts") == before
    assert database.scalar("SELECT COUNT(*) FROM tasks") == 0


def test_record_without_valid_sha_is_not_ready(api):
    database = api.app.state.services.database
    database.execute(
        """INSERT INTO projects
           (project_id, title, project_type, source_app, classification,
            status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("nohash-project", "Fixture", "pet", "test", "internal", "Active",
         "2026-11-19T00:00:00Z", "2026-11-19T00:00:00Z"),
    )
    database.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, artifact_type, classification,
            sha256, is_original, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("backyard_v1", "nohash-project", "image", "internal", "invalid", 0,
         "2026-11-19T00:00:00Z"),
    )
    result = api.post("/api/v1/studio/storypacks/preview", json=storypack())
    assert result.status_code == 200
    checks = {item["ref"]: item for item in result.json()["asset_record_checks"]}
    assert checks["backyard_v1"]["registry_record_status"] == "RECORD_HASH_MISSING"
    assert checks["backyard_v1"]["sha256_recorded"] is False
    assert checks["backyard_v1"]["usable_for_generation"] is False
    assert result.json()["can_queue"] is False


def test_portrait_preview_does_not_enable_rendering(api):
    pack = storypack()
    pack["output_profile"] = "design_portrait"
    response = api.post("/api/v1/studio/storypacks/preview", json=pack)
    assert response.status_code == 200
    assert response.json()["output"]["height"] == 832
    assert response.json()["can_queue"] is False
