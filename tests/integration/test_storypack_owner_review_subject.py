"""Owner review subject is a digest-only preview, never a permission grant."""

from __future__ import annotations

import copy
import secrets

import pytest
from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.domain.storypack import StoryPackV1, storypack_preview
from picotoopet_core.domain.storypack_owner_subject import build_owner_review_subject


def _pack_data() -> dict:
    return {
        "schema": "picotoo.storypack.v1",
        "episode_id": "maotai_ep02",
        "title": "Homecoming",
        "output_profile": "p0_landscape",
        "character_ref": "maotai_master_v1",
        "supporting_character_refs": ["friend_master_v1"],
        "scene_ref": "backyard_v1",
        "additional_scene_refs": ["front_door_v1"],
        "style_ref": "toon_style_v1",
        "story": {"goal": "Find dinner", "payoff": "Come home"},
        "shots": [
            {
                "id": "S01",
                "action": "Run in the yard",
                "state_in": "Outside",
                "state_out": "At door",
                "because": "Hungry",
            },
            {
                "id": "S02",
                "action": "Meet a friend",
                "state_in": "At door",
                "state_out": "Together",
                "because": "Hear footsteps",
                "scene_ref": "front_door_v1",
                "cast_refs": ["maotai_master_v1", "friend_master_v1"],
                "depends_on": ["S01"],
                "handoff": "scene_change",
            },
        ],
    }


def _checks(pack: StoryPackV1) -> list[dict]:
    refs = [
        pack.character_ref,
        *pack.supporting_character_refs,
        pack.scene_ref,
        *pack.additional_scene_refs,
        *([] if pack.style_ref is None else [pack.style_ref]),
    ]
    return [
        {
            "ref": ref,
            "recorded_sha256": f"{index + 1:064x}",
            "sha256_recorded": True,
            "managed_object_integrity": "CONTENT_VERIFIED_UNAPPROVED",
            "content_integrity_verified": True,
            "physical_file_verified": True,
            "artifact_type": "image",
            "owner_approval_verified": False,
            "usable_for_generation": False,
        }
        for index, ref in enumerate(dict.fromkeys(refs))
    ]


def _subject(data: dict, *, checks: list[dict] | None = None) -> dict:
    pack = StoryPackV1.model_validate(data)
    digest = storypack_preview(pack)["storypack_sha256"]
    return build_owner_review_subject(
        pack, digest, _checks(pack) if checks is None else checks
    )


def test_verified_managed_bytes_produce_stable_unapproved_scope():
    data = _pack_data()
    a = _subject(data)
    b = _subject(copy.deepcopy(data))
    assert a == b
    assert a["status"] == "REVIEW_SUBJECT_PREPARED_UNAPPROVED"
    assert len(a["subject_sha256"]) == 64
    assert a["owner_approved"] is False
    assert a["can_queue"] is False
    assert a["requires_reverification_at_decision"] is True
    assert a["subject"]["shot_bindings"][1]["scene_ref"] == "front_door_v1"
    assert a["subject"]["shot_bindings"][1]["cast_refs"] == [
        "maotai_master_v1", "friend_master_v1",
    ]
    assert "request_gpu_generation" in a["proposed_permissions"]


def test_story_action_asset_digest_scene_and_scope_are_locked():
    original = _pack_data()
    base = _subject(original)["subject_sha256"]
    action = copy.deepcopy(original)
    action["shots"][0]["action"] = "Walk instead"
    assert _subject(action)["subject_sha256"] != base

    new_scene = copy.deepcopy(original)
    new_scene["additional_scene_refs"] = ["front_door_v2"]
    new_scene["shots"][1]["scene_ref"] = "front_door_v2"
    assert _subject(new_scene)["subject_sha256"] != base

    pack = StoryPackV1.model_validate(original)
    changed_checks = _checks(pack)
    changed_checks[1]["recorded_sha256"] = "f" * 64
    assert _subject(original, checks=changed_checks)["subject_sha256"] != base


@pytest.mark.parametrize("reason", [
    "missing", "unreadable", "missing_sha", "fake_check", "duplicate", "extra",
])
def test_unverified_or_mismatched_asset_evidence_never_gets_a_digest(reason):
    data = _pack_data()
    checks = _checks(StoryPackV1.model_validate(data))
    if reason == "missing":
        checks.pop()
    elif reason == "unreadable":
        checks[0]["content_integrity_verified"] = False
    elif reason == "missing_sha":
        checks[0]["recorded_sha256"] = None
    elif reason == "fake_check":
        checks[0]["managed_object_integrity"] = "NOT_CHECKED"
    elif reason == "duplicate":
        checks.append(copy.deepcopy(checks[0]))
    else:
        extra = copy.deepcopy(checks[0])
        extra["ref"] = "unexpected_new_master"
        checks.append(extra)
    result = _subject(data, checks=checks)
    assert result["status"] == "BLOCKED_INCOMPLETE_EVIDENCE"
    assert result["subject_sha256"] is None
    assert result["blocking_reasons"]
    assert result["owner_approved"] is False
    assert result["can_queue"] is False


def test_missing_style_prevents_owner_review_digest():
    data = _pack_data()
    data["style_ref"] = None
    result = _subject(data)
    assert "STYLE_LOCK_MISSING" in result["blocking_reasons"]
    assert result["subject_sha256"] is None


def test_forged_owner_approval_flag_cannot_approve_subject():
    data = _pack_data()
    checks = _checks(StoryPackV1.model_validate(data))
    for row in checks:
        row["owner_approval_verified"] = True
        row["usable_for_generation"] = True
    result = _subject(data, checks=checks)
    assert result["owner_approved"] is False
    assert result["can_queue"] is False


@pytest.fixture
def api(tmp_path):
    token = secrets.token_hex(24)
    app = create_app(AppSettings(paths=RuntimePaths.from_root(tmp_path), api_token=token))
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        yield client


def _register_managed_fixture(api, ref: str) -> None:
    services = api.app.state.services
    stored = services.results.put_bytes(("asset:" + ref).encode(), result_type="image")
    services.database.execute(
        """INSERT OR IGNORE INTO projects
           (project_id, title, project_type, source_app, classification, status,
            created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "owner-subject-test", "Review fixture", "pet", "test", "internal", "Active",
            "2026-11-19T00:00:00Z", "2026-11-19T00:00:00Z",
        ),
    )
    services.database.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, artifact_type, classification, sha256,
            stored_object_hash, is_original, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            ref, "owner-subject-test", "image", "internal", stored.object_hash,
            stored.object_hash, 1, "2026-11-19T00:00:00Z",
        ),
    )


def test_real_studio_preview_subject_never_issues_approval_or_queue(api):
    data = _pack_data()
    refs = [
        data["character_ref"], *data["supporting_character_refs"],
        data["scene_ref"], *data["additional_scene_refs"], data["style_ref"],
    ]
    for ref in refs:
        _register_managed_fixture(api, ref)

    endpoint = "/api/v1/studio/storypacks/preview"
    first = api.post(endpoint, json=data)
    assert first.status_code == 200
    result = first.json()
    subject = result["owner_review_subject"]
    assert subject["status"] == "REVIEW_SUBJECT_PREPARED_UNAPPROVED"
    assert len(subject["subject_sha256"]) == 64
    assert subject["subject"]["storypack_sha256"] == result["storypack_sha256"]
    assert result["can_queue"] is False
    assert result["production_compilation"]["can_queue"] is False

    denied = api.post(endpoint, json=data, headers={"Authorization": "Bearer invalid"})
    assert denied.status_code == 401
    second = api.post(endpoint, json=data)
    assert second.json()["owner_review_subject"]["subject_sha256"] == subject["subject_sha256"]

    # 本轮仅生成审核摘要：原有任务、审批与生产记录均不能新增。
    db = api.app.state.services.database
    assert db.scalar("SELECT COUNT(*) FROM tasks") == 0
    assert db.scalar("SELECT COUNT(*) FROM approvals") == 0
    assert db.scalar("SELECT COUNT(*) FROM episodes") == 0


def test_studio_preview_missing_asset_blocks_subject(api):
    response = api.post("/api/v1/studio/storypacks/preview", json=_pack_data())
    assert response.status_code == 200
    subject = response.json()["owner_review_subject"]
    assert subject["subject_sha256"] is None
    assert any(x.startswith("ASSET_CONTENT_UNVERIFIED:") for x in subject["blocking_reasons"])
    assert response.json()["can_queue"] is False
