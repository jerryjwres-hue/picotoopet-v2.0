"""P0-2 offline bridge evidence: no synthetic production authorization.

All fixtures are fabricated. Real Windows StoryPack and private assets are NOT
imported, approved, moved, submitted or embedded in this public test suite.
"""

from __future__ import annotations

import hashlib
import json
import secrets

import pytest
from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.domain.storypack import parse_storypack, storypack_preview
from picotoopet_core.domain.storypack_plan_bridge import build_storypack_bridge_proposal

CHARACTER = "asset-" + "a" * 64
SCENE = "asset-" + "b" * 64
STYLE = "asset-" + "c" * 64
SECOND_SCENE = "asset-" + "d" * 64


def _pack(**overrides):
    # 01. Three real distinct story beats, fully deterministic synthetic
    #     state handoffs, no GPU, no user-owned images.
    value = {
        "schema": "picotoo.storypack.v1",
        "episode_id": "test-three-shot-meal",
        "title": "Test dog dinner",
        "output_profile": "p0_landscape",
        "character_ref": CHARACTER,
        "scene_ref": SCENE,
        "style_ref": STYLE,
        "story": {"goal": "The dog wants dinner", "payoff": "Dog eats"},
        "shots": [
            {"id": "S01", "action": "Sniff food", "state_in": "by the door",
             "state_out": "looking at bowl", "because": "smells dinner"},
            {"id": "S02", "action": "Walk to bowl", "state_in": "looking at bowl",
             "state_out": "near bowl", "because": "bowl is nearby",
             "depends_on": ["S01"], "handoff": "continuous"},
            {"id": "S03", "action": "Eat food", "state_in": "near bowl",
             "state_out": "eating", "because": "hungry",
             "depends_on": ["S02"], "handoff": "continuous"},
        ],
    }
    value.update(overrides)
    return value


def _parse(**overrides):
    return parse_storypack(json.dumps(_pack(**overrides)).encode("utf-8"))


def _checks(*, approved=False, absent=False, scene_claim=False, extra=None):
    checks = []
    for ref, kind in [(CHARACTER, "character_master"), (SCENE, "scene_master"),
                      (STYLE, "identity_lock")]:
        checks.append({
            "ref": ref,
            "registry_record_status": "RECORD_NOT_FOUND" if absent else "RECORDED_UNAPPROVED",
            "kind_check": "RECORD_NOT_FOUND" if absent else "KIND_MATCHES_SLOT",
            "asset_kind": None if absent else kind,
            "recorded_sha256": None if absent else hashlib.sha256(ref.encode()).hexdigest(),
            "byte_provenance": (
                None if absent else
                "WINDOWS_CLIENT_CLAIM_NOT_CORE_HASHED"
                if ref == SCENE and scene_claim else "CORE_HASHED_MANAGED_COPY"
            ),
            "content_integrity_verified": not absent and not (ref == SCENE and scene_claim),
            "owner_approval_verified": approved,
        })
    return checks + (extra or [])


def _proposal(pack, checks):
    return build_storypack_bridge_proposal(
        pack, storypack_preview(pack)["storypack_sha256"], checks,
    )


def test_frozen_proposal_preserves_three_distinct_story_beats_and_source_immutability():
    pack = _parse()
    before = pack.model_dump(mode="json")
    preview = _proposal(pack, _checks())
    assert preview == _proposal(pack, _checks())
    assert preview["source_storypack_rewritten"] is False
    assert preview["source_storypack_sha256"] == storypack_preview(pack)["storypack_sha256"]
    assert preview["proposal_sha256"] == hashlib.sha256(json.dumps({
        key: preview[key] for key in (
            "schema", "bridge_version", "source_schema", "source_storypack_sha256",
            "episode_id", "title", "output_profile", "output", "story", "assets", "shots"
        )
    }, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    assert pack.model_dump(mode="json") == before
    assert [shot["action"] for shot in preview["shots"]] == [
        "Sniff food", "Walk to bowl", "Eat food"
    ]
    assert [shot["state_out"] for shot in preview["shots"]] == [
        "looking at bowl", "near bowl", "eating"
    ]
    assert [shot["depends_on"] for shot in preview["shots"]] == [
        [], ["S01"], ["S02"]
    ]
    assert all(shot["character_artifact_ids"] == [CHARACTER] for shot in preview["shots"])
    assert all(shot["scene_artifact_id"] == SCENE for shot in preview["shots"])
    assert all(shot["style_artifact_id"] == STYLE for shot in preview["shots"])
    assert all(shot["trusted_first_frame_artifact_id"] is None for shot in preview["shots"])
    assert all(shot["render_intent_proposed"] == "IMAGE_TO_VIDEO" for shot in preview["shots"])
    assert all(shot["execution_disposition"] == "NEEDS_HUMAN" for shot in preview["shots"])
    assert all((shot["width"], shot["height"], shot["frame_count"]) == (832, 480, 97)
               for shot in preview["shots"])
    assert preview["output_profile"] == "p0_landscape"
    assert preview["production_plan_created"] is False
    assert preview["production_plan_executable"] is False
    assert preview["gpu_post_authorized"] is False
    assert preview["can_queue"] is False


def test_approved_assets_still_do_not_fabricate_first_frames_or_gpu_authority():
    # 02. Even three Owner-approved, Core-byte-verified MASTER assets are not
    #     the three I2V frames, a frozen Creative Package, or renderer grant.
    proposal = _proposal(_parse(), _checks(approved=True))
    assert all(asset["owner_approved"] for asset in proposal["assets"])
    assert all(asset["core_verified_bytes"] for asset in proposal["assets"])
    assert proposal["bridge_status"] == "NEEDS_HUMAN"
    assert "STORYPACK_ASSET_OWNER_APPROVAL_MISSING" not in proposal["blocking_reasons"]
    assert "STORYPACK_PER_SHOT_FIRST_FRAMES_NOT_BOUND" in proposal["blocking_reasons"]
    assert "STORYPACK_FROZEN_CREATIVE_PACKAGE_NOT_ESTABLISHED" in proposal["blocking_reasons"]
    assert proposal["production_plan_executable"] is False
    assert proposal["gpu_post_authorized"] is False


def test_unregistered_names_wrong_kind_and_windows_sha_claim_stay_unverified():
    # 03. Real 11-21 StoryPack uses names; names must not be quietly
    #     promoted to fabricated canonical artifact IDs.
    named = _parse(character_ref="MASTER_body_C8B_v1",
                   scene_ref="PL3b_E_dogeye_in_strip_v2",
                   style_ref="MAOTAI_IDENTITY_LOCK_v2")
    checks = [
        {**entry, "ref": old, "registry_record_status": "RECORD_NOT_FOUND",
         "recorded_sha256": None, "kind_check": "RECORD_NOT_FOUND",
         "asset_kind": None, "byte_provenance": None,
         "owner_approval_verified": False, "content_integrity_verified": False}
        for entry, old in zip(_checks(), (
            "MASTER_body_C8B_v1", "PL3b_E_dogeye_in_strip_v2",
            "MAOTAI_IDENTITY_LOCK_v2",
        ), strict=True)
    ]
    proposal = _proposal(named, checks)
    assert "STORYPACK_REF_NOT_CANONICAL_CORE_ID" in proposal["blocking_reasons"]
    assert "STORYPACK_ASSET_RECORD_NOT_FOUND" in proposal["blocking_reasons"]
    assert all(item["artifact_id"] is None for item in proposal["assets"])
    assert proposal["can_queue"] is False

    claim_checks = _checks(approved=True, scene_claim=True)
    claim = _proposal(_parse(), claim_checks)
    assert next(item for item in claim["assets"] if item["source_ref"] == SCENE)[
        "requires_windows_byte_check"
    ] is True
    assert claim["production_plan_executable"] is False
    wrong = _checks(approved=True)
    wrong[0]["asset_kind"] = "scene_master"
    assert "STORYPACK_ASSET_KIND_MISMATCH" in _proposal(_parse(), wrong)["blocking_reasons"]


def test_missing_duplicate_checks_or_bad_digest_fail_closed():
    pack = _parse()
    digest = storypack_preview(pack)["storypack_sha256"]
    for checks in (_checks()[:2], _checks() + [_checks()[0]],
                   _checks() + [{"ref": "unrelated"}]):
        with pytest.raises(ValueError, match="STORYPACK_BRIDGE_ASSET_CHECKS_"):
            build_storypack_bridge_proposal(pack, digest, checks)
    with pytest.raises(ValueError, match="STORYPACK_BRIDGE_SOURCE_DIGEST_INVALID"):
        build_storypack_bridge_proposal(pack, "abc", _checks())


def test_portrait_is_preserved_as_proposal_without_rewriting_original_pack():
    # 04. "Design portrait" is only a user-selected profile, not an
    #     implied rewrite of the real 11-21 p0_landscape StoryPack.
    source = _parse(output_profile="design_portrait")
    proposal = _proposal(source, _checks())
    assert proposal["output_profile"] == "design_portrait"
    assert proposal["output"] == {
        "width": 480, "height": 832, "fps": 24, "frames_per_shot": 97,
    }
    assert all((shot["width"], shot["height"]) == (480, 832)
               for shot in proposal["shots"])
    assert proposal["source_storypack_rewritten"] is False
    assert proposal["gpu_post_authorized"] is False


def test_preview_api_exposes_immutable_bridge_without_mutating_database(tmp_path):
    # 05. Real Core route still only PREVIEWS; no SQLite record, Goal,
    #     approval, Worker task, or Comfy POST can result.
    token = secrets.token_hex(24)
    app = create_app(AppSettings(paths=RuntimePaths.from_root(tmp_path), api_token=token))
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        before = client.app.state.services.database.scalar(
            "SELECT COUNT(*) FROM artifacts"
        )
        response = client.post("/api/v1/studio/storypacks/preview", json=_pack())
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["storypack_sha256"] == data["production_bridge_proposal"][
            "source_storypack_sha256"
        ]
        assert data["production_bridge_proposal"]["bridge_status"] == "NEEDS_HUMAN"
        assert "STORYPACK_ASSET_RECORD_NOT_FOUND" in data[
            "production_bridge_proposal"]["blocking_reasons"]
        assert data["core23_compatibility"]["executable_plan"] is False
        assert data["production_bridge_proposal"]["production_plan_created"] is False
        assert data["production_bridge_proposal"]["gpu_post_authorized"] is False
        assert client.app.state.services.database.scalar(
            "SELECT COUNT(*) FROM artifacts"
        ) == before
