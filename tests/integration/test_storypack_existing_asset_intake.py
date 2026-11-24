"""P0-1: existing Maotai assets enter Core through the existing artifacts/approvals path.

No second registry table, no second approval system, no schema bump. A Windows byte
claim stays a claim: Core never says it hashed bytes it cannot read.
"""

from __future__ import annotations

import base64
import hashlib
import secrets

import pytest
from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.db.database import CURRENT_SCHEMA_VERSION

PREVIEW = "/api/v1/studio/storypacks/preview"
IMPORT = "/api/v1/studio/assets/import"
WINDOWS_CLAIM = "/api/v1/studio/assets/windows-evidence"
BY_SHA = "/api/v1/studio/assets/by-sha256"

# Real hashes from the 2026-11-23 Windows read-only inventory (test data only;
# using them never grants Owner approval).
LORA_V2_SHA = "5972e7f782e3e4ed16b764441fdb66d638cb6a8ba85fb8226d95feeb98e8eb70"
LORA_V2_BYTES = 46_223_616
C8B_SHA = "c6d7e556b8047d06d6ba7c408e8fdde26d3d16dd59d3c029e901847beac8f59b"

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+XgZsAAAAASUVORK5CYII="
)
_SCENE_PNG = _PNG + b"\x00scene"  # distinct bytes; signature check only reads the header


@pytest.fixture
def studio(tmp_path):
    token = secrets.token_hex(24)
    app = create_app(AppSettings(paths=RuntimePaths.from_root(tmp_path), api_token=token))
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        yield client


def _project(studio) -> str:
    response = studio.post("/api/v1/projects", json={
        "title": "Maotai intake fixture", "project_type": "film", "source_app": "test",
        "classification": "INTERNAL",
    })
    assert response.status_code == 201, response.text
    return response.json()["project_id"]


def _import(studio, project, role, data, media="image/png"):
    response = studio.post(IMPORT, content=data, headers={
        "X-Picotoo-Project-Id": project,
        "X-Picotoo-Asset-Role": role,
        "X-Picotoo-Asset-SHA256": hashlib.sha256(data).hexdigest(),
        "X-Picotoo-Import-Confirmed": "yes",
        "Content-Type": media,
    })
    assert response.status_code == 201, response.text
    return response.json()["artifact_id"]


def _evidence(**overrides):
    evidence = {
        "method": "windows_full_file_sha256",
        "verified_at": "2026-11-23T23:30:00+00:00",
        "verifier": "windows-claude-readonly-inventory",
        "file_name": "maotai_lora_v2.safetensors",
    }
    evidence.update(overrides)
    return evidence


def _claim_body(project, **overrides):
    body = {
        "project_id": project,
        "asset_kind": "lora",
        "sha256": LORA_V2_SHA,
        "size_bytes": LORA_V2_BYTES,
        "media_type": "application/octet-stream",
        "windows_evidence": _evidence(),
        "confirmed": True,
    }
    body.update(overrides)
    return body


def _request_approval(studio, artifact_id, sha, **extra):
    return studio.post(f"/api/v1/studio/assets/{artifact_id}/owner-approval-request",
                       json={"expected_sha256": sha, **extra})


def _decide(studio, approval, decision):
    response = studio.post(
        f"/api/v1/approvals/{approval['approval_id']}/decision",
        json={"decision": decision, "request_digest": approval["request_digest"],
              "reason": f"owner {decision} in Control Center"},
        headers={"Idempotency-Key": secrets.token_hex(8)},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _eligibility(studio, artifact_id):
    response = studio.get(f"/api/v1/studio/assets/{artifact_id}/production-eligibility")
    assert response.status_code == 200, response.text
    return response.json()


def _tables(studio) -> set[str]:
    db = studio.app.state.services.database
    return {row["name"] for row in db.fetchall(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def _storypack(**refs):
    pack = {
        "schema": "picotoo.storypack.v1",
        "episode_id": "maotai-meal-three-shot-acceptance",
        "title": "Maotai finds dinner",
        "output_profile": "p0_landscape",
        "character_ref": "MASTER_body_C8B_v1",
        "scene_ref": "PL3b_E_dogeye_in_strip_v2",
        "style_ref": "MAOTAI_IDENTITY_LOCK_v2",
        "story": {"goal": "Maotai finds his bowl", "payoff": "Maotai eats chicken"},
        "shots": [
            {"id": "S01", "action": "Maotai smells dinner", "state_in": "left",
             "state_out": "looking right", "because": "chicken smell"},
            {"id": "S02", "action": "Maotai walks to the bowl", "state_in": "looking right",
             "state_out": "at bowl", "because": "bowl spotted", "depends_on": ["S01"],
             "handoff": "continuous"},
            {"id": "S03", "action": "Maotai eats", "state_in": "at bowl",
             "state_out": "eating", "because": "he is at the bowl", "depends_on": ["S02"],
             "handoff": "continuous"},
        ],
    }
    pack.update(refs)
    return pack


def test_kinds_map_onto_existing_artifact_types_without_new_tables(studio):
    before = _tables(studio)
    project = _project(studio)
    ids = {
        "character_master": _import(studio, project, "character", _PNG),
        "scene_master": _import(studio, project, "scene", _SCENE_PNG),
        "identity_lock": _import(studio, project, "style", b"Maotai identity lock v2",
                                 "text/plain"),
    }
    claim = studio.post(WINDOWS_CLAIM, json=_claim_body(project))
    assert claim.status_code == 201, claim.text
    ids["lora"] = claim.json()["artifact_id"]
    workflow = studio.post(WINDOWS_CLAIM, json=_claim_body(
        project, asset_kind="workflow", sha256="ab" * 32, size_bytes=4096,
        media_type="application/json",
        windows_evidence=_evidence(file_name="run_flux_board.py"),
    ))
    assert workflow.status_code == 201, workflow.text
    ids["workflow"] = workflow.json()["artifact_id"]

    db = studio.app.state.services.database
    types = {row["artifact_id"]: row["artifact_type"] for row in db.fetchall(
        "SELECT artifact_id, artifact_type FROM artifacts")}
    assert types == {
        ids["character_master"]: "storypack_character",
        ids["scene_master"]: "storypack_scene",
        ids["identity_lock"]: "storypack_style",
        ids["lora"]: "storypack_lora",
        ids["workflow"]: "storypack_workflow",
    }
    # Reuse only: no new table, no schema bump.
    assert _tables(studio) == before
    assert CURRENT_SCHEMA_VERSION == 24
    assert db.scalar("SELECT MAX(version) FROM schema_migrations") == 24

    found = studio.get(BY_SHA, params={"sha256": hashlib.sha256(_PNG).hexdigest()})
    assert found.status_code == 200, found.text
    match = found.json()["matches"]
    assert [item["artifact_id"] for item in match] == [ids["character_master"]]
    assert match[0]["asset_kind"] == "character_master"
    assert match[0]["byte_provenance"] == "CORE_HASHED_MANAGED_COPY"
    assert match[0]["owner_approval_status"] == "NOT_REQUESTED"
    assert match[0]["production_eligible"] is False


def test_windows_lora_claim_is_registered_but_never_called_core_verified(studio):
    project = _project(studio)
    first = studio.post(WINDOWS_CLAIM, json=_claim_body(project))
    assert first.status_code == 201, first.text
    receipt = first.json()
    assert receipt["artifact_id"].startswith("asset-")
    assert receipt["registration"] == "CREATED"
    assert receipt["asset_kind"] == "lora"
    assert receipt["byte_provenance"] == "WINDOWS_CLIENT_CLAIM_NOT_CORE_HASHED"
    assert receipt["core_verified_bytes"] is False
    assert all(receipt[key] is False for key in (
        "owner_approved", "can_queue", "gpu_post_authorized"))
    db = studio.app.state.services.database
    row = db.fetchone("SELECT * FROM artifacts WHERE artifact_id=?", (receipt["artifact_id"],))
    assert row["stored_object_hash"] is None and row["source_path"] is None
    assert row["sha256"] == LORA_V2_SHA and row["size_bytes"] == LORA_V2_BYTES

    replay = studio.post(WINDOWS_CLAIM, json=_claim_body(project))
    assert replay.status_code == 201
    assert replay.json()["artifact_id"] == receipt["artifact_id"]
    assert replay.json()["registration"] == "REPLAY"
    assert db.scalar("SELECT COUNT(*) FROM artifacts") == 1

    conflict = studio.post(WINDOWS_CLAIM, json=_claim_body(project, size_bytes=LORA_V2_BYTES + 1))
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "ASSET_REPLAY_CONFLICT"

    # Full SHA lookup returns the real artifact id; uppercase input is normalized.
    found = studio.get(BY_SHA, params={"sha256": LORA_V2_SHA.upper(), "project_id": project})
    assert found.status_code == 200
    assert [m["artifact_id"] for m in found.json()["matches"]] == [receipt["artifact_id"]]
    assert found.json()["matches"][0]["byte_provenance"] == "WINDOWS_CLIENT_CLAIM_NOT_CORE_HASHED"


@pytest.mark.parametrize("case,status,code", [
    ("image_kind_needs_core_copy", 409, "ASSET_KIND_REQUIRES_CORE_COPY"),
    ("unknown_kind", 422, None),
    ("short_sha", 422, None),
    ("windows_path_in_evidence", 422, None),
    ("not_confirmed", 422, None),
    ("missing_project", 409, "ASSET_PROJECT_UNAVAILABLE"),
    ("oversize_workflow", 409, "ASSET_SIZE_INVALID"),
    ("naive_timestamp", 422, None),
])
def test_windows_claim_rejections_write_nothing(studio, case, status, code):
    project = _project(studio)
    body = _claim_body(project)
    if case == "image_kind_needs_core_copy":
        body.update(asset_kind="character_master", sha256=C8B_SHA, size_bytes=1_075_640,
                    media_type="image/png")
    elif case == "unknown_kind":
        body["asset_kind"] = "master_anything"
    elif case == "short_sha":
        body["sha256"] = LORA_V2_SHA[:8]
    elif case == "windows_path_in_evidence":
        body["windows_evidence"] = _evidence(file_name="D:\\opc in D\\maotai_lora_v2.safetensors")
    elif case == "not_confirmed":
        body["confirmed"] = False
    elif case == "missing_project":
        body["project_id"] = "missing"
    elif case == "oversize_workflow":
        body.update(asset_kind="workflow", media_type="application/json",
                    size_bytes=3 * 1024 * 1024)
    else:
        body["windows_evidence"] = _evidence(verified_at="2026-11-23T23:30:00")
    response = studio.post(WINDOWS_CLAIM, json=body)
    assert response.status_code == status, response.text
    if code:
        assert response.json()["error"]["code"] == code
    db = studio.app.state.services.database
    assert db.scalar("SELECT COUNT(*) FROM artifacts") == 0
    assert db.scalar("SELECT COUNT(*) FROM approvals") == 0


def test_by_sha_requires_full_digest_and_returns_empty_without_inventing_ids(studio):
    assert studio.get(BY_SHA, params={"sha256": C8B_SHA[:8]}).status_code == 422
    empty = studio.get(BY_SHA, params={"sha256": C8B_SHA})
    assert empty.status_code == 200
    assert empty.json() == {"sha256": C8B_SHA, "match_count": 0, "matches": []}
    assert studio.app.state.services.database.scalar("SELECT COUNT(*) FROM artifacts") == 0


def test_unapproved_assets_never_gain_production_eligibility(studio):
    project = _project(studio)
    character = _import(studio, project, "character", _PNG)
    sha = hashlib.sha256(_PNG).hexdigest()
    assert _eligibility(studio, character) | {} == {
        "artifact_id": character, "asset_kind": "character_master",
        "byte_provenance": "CORE_HASHED_MANAGED_COPY",
        "owner_approval_status": "NOT_REQUESTED", "approval_id": None,
        "eligible": False, "reason": "OWNER_APPROVAL_NOT_REQUESTED",
        "core_verified_bytes": True, "requires_windows_byte_check_before_use": True,
        "gpu_post_authorized": False,
    }

    wrong = _request_approval(studio, character, "0" * 64)
    assert wrong.status_code == 409
    assert wrong.json()["error"]["code"] == "ASSET_SHA_MISMATCH"

    pending = _request_approval(studio, character, sha)
    assert pending.status_code == 201, pending.text
    approval = pending.json()
    assert approval["status"] == "Pending"
    assert approval["approval_type"] == "storypack.asset_owner_approval.v1"
    again = _request_approval(studio, character, sha)
    assert again.json()["approval_id"] == approval["approval_id"]
    assert studio.app.state.services.database.scalar("SELECT COUNT(*) FROM approvals") == 1
    state = _eligibility(studio, character)
    assert (state["eligible"], state["reason"]) == (False, "OWNER_APPROVAL_PENDING")

    _decide(studio, approval, "reject")
    state = _eligibility(studio, character)
    assert (state["eligible"], state["reason"]) == (False, "OWNER_APPROVAL_REJECTED")

    second = _request_approval(studio, character, sha).json()
    assert second["approval_id"] != approval["approval_id"]
    _decide(studio, second, "approve")
    state = _eligibility(studio, character)
    assert state["eligible"] is True
    assert state["reason"] == "OWNER_APPROVED"
    assert state["approval_id"] == second["approval_id"]
    # Eligibility is reference eligibility only; it never authorizes a GPU post.
    assert state["gpu_post_authorized"] is False


def test_approval_is_bound_to_bytes_and_tampering_revokes_eligibility(studio):
    project = _project(studio)
    character = _import(studio, project, "character", _PNG)
    sha = hashlib.sha256(_PNG).hexdigest()
    _decide(studio, _request_approval(studio, character, sha).json(), "approve")
    assert _eligibility(studio, character)["eligible"] is True

    store = studio.app.state.services.results
    (store.objects_dir / sha[:2] / sha[2:]).write_bytes(b"tampered")
    state = _eligibility(studio, character)
    assert (state["eligible"], state["reason"]) == (False, "CORE_COPY_INTEGRITY_FAILED")


def test_windows_claim_approval_requires_evidence_and_stays_a_claim(studio):
    project = _project(studio)
    lora = studio.post(WINDOWS_CLAIM, json=_claim_body(project)).json()["artifact_id"]
    missing = _request_approval(studio, lora, LORA_V2_SHA)
    assert missing.status_code == 409
    assert missing.json()["error"]["code"] == "ASSET_WINDOWS_EVIDENCE_REQUIRED"

    approval = _request_approval(studio, lora, LORA_V2_SHA, windows_evidence=_evidence())
    assert approval.status_code == 201, approval.text
    record = studio.app.state.services.approvals.get(approval.json()["approval_id"])
    assert record.scope["byte_provenance"] == "WINDOWS_CLIENT_CLAIM_NOT_CORE_HASHED"
    assert record.scope["windows_evidence"]["file_name"] == "maotai_lora_v2.safetensors"
    assert record.scope["sha256"] == LORA_V2_SHA
    _decide(studio, approval.json(), "approve")
    state = _eligibility(studio, lora)
    assert state["eligible"] is True
    assert state["core_verified_bytes"] is False
    assert state["requires_windows_byte_check_before_use"] is True


def test_unknown_artifact_eligibility_and_approval_fail_closed(studio):
    fake = "asset-" + "1" * 64
    state = _eligibility(studio, fake)
    assert (state["eligible"], state["reason"]) == (False, "ARTIFACT_NOT_REGISTERED")
    assert _request_approval(studio, fake, "1" * 64).status_code == 404
    assert studio.app.state.services.database.scalar("SELECT COUNT(*) FROM approvals") == 0


def test_preview_explains_missing_assets_without_creating_ids(studio):
    before = studio.app.state.services.database.scalar("SELECT COUNT(*) FROM artifacts")
    unregistered = "asset-" + "2" * 64
    response = studio.post(PREVIEW, json=_storypack(scene_ref=unregistered))
    assert response.status_code == 200, response.text
    checks = {item["ref"]: item for item in response.json()["asset_record_checks"]}
    assert checks["MASTER_body_C8B_v1"]["registry_record_status"] == "RECORD_NOT_FOUND"
    assert checks["MASTER_body_C8B_v1"]["missing_reason"] == "REF_IS_NOT_A_CORE_ARTIFACT_ID"
    assert checks[unregistered]["missing_reason"] == "ARTIFACT_NOT_REGISTERED"
    assert checks["MASTER_body_C8B_v1"]["expected_asset_kind"] == "character_master"
    assert checks[unregistered]["expected_asset_kind"] == "scene_master"
    assert checks["MAOTAI_IDENTITY_LOCK_v2"]["expected_asset_kind"] == "identity_lock"
    assert all(item["asset_kind"] is None and not item["usable_for_generation"]
               for item in checks.values())
    after = studio.app.state.services.database.scalar("SELECT COUNT(*) FROM artifacts")
    assert after == before == 0


def test_preview_flags_wrong_asset_kind_in_slot(studio):
    project = _project(studio)
    scene = _import(studio, project, "scene", _SCENE_PNG)
    lora = studio.post(WINDOWS_CLAIM, json=_claim_body(project)).json()["artifact_id"]
    response = studio.post(PREVIEW, json=_storypack(character_ref=lora, scene_ref=scene))
    assert response.status_code == 200, response.text
    checks = {item["ref"]: item for item in response.json()["asset_record_checks"]}
    assert checks[lora]["asset_kind"] == "lora"
    assert checks[lora]["kind_check"] == "ARTIFACT_KIND_MISMATCH"
    assert checks[scene]["kind_check"] == "KIND_MATCHES_SLOT"
    assert all(not item["usable_for_generation"] for item in checks.values())


def test_preview_reports_owner_approval_but_never_queues(studio):
    project = _project(studio)
    refs = {
        "character_ref": _import(studio, project, "character", _PNG),
        "scene_ref": _import(studio, project, "scene", _SCENE_PNG),
        "style_ref": _import(studio, project, "style", b"Maotai lock", "text/plain"),
    }
    sha = hashlib.sha256(_PNG).hexdigest()
    _decide(studio, _request_approval(studio, refs["character_ref"], sha).json(), "approve")
    result = studio.post(PREVIEW, json=_storypack(**refs)).json()
    checks = {item["ref"]: item for item in result["asset_record_checks"]}
    character = checks[refs["character_ref"]]
    assert character["owner_approval_status"] == "APPROVED"
    assert character["owner_approval_verified"] is True
    assert checks[refs["scene_ref"]]["owner_approval_status"] == "NOT_REQUESTED"
    assert checks[refs["scene_ref"]]["owner_approval_verified"] is False
    assert all(not item["usable_for_generation"] for item in checks.values())
    assert result["can_queue"] is False
    assert result["core23_compatibility"]["gpu_post_authorized"] is False


def test_legacy_artifact_rows_remain_compatible(studio):
    project = _project(studio)
    db = studio.app.state.services.database
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO artifacts (artifact_id, project_id, artifact_type, classification, "
            "source_path, stored_object_hash, media_type, size_bytes, sha256, is_original, "
            "cloud_policy, created_at) VALUES (?, ?, 'legacy_render', 'INTERNAL', NULL, NULL, "
            "'video/mp4', 10, NULL, 1, 'local_only', '2026-11-01T00:00:00+00:00')",
            ("legacy-artifact-1", project),
        )
    response = studio.post(PREVIEW, json=_storypack(character_ref="legacy-artifact-1"))
    assert response.status_code == 200, response.text
    check = {i["ref"]: i for i in response.json()["asset_record_checks"]}["legacy-artifact-1"]
    # Old fields keep their old meaning; new fields are additive.
    assert check["registry_record_status"] == "RECORD_HASH_MISSING"
    assert check["artifact_type"] == "legacy_render"
    assert check["missing_reason"] is None
    assert check["asset_kind"] is None
    assert check["kind_check"] == "ARTIFACT_KIND_MISMATCH"
    assert _eligibility(studio, "legacy-artifact-1")["reason"] == "ARTIFACT_NOT_STORYPACK_ASSET"
    assert studio.get(BY_SHA, params={"sha256": "0" * 64}).json()["match_count"] == 0


def test_control_center_summary_names_kind_and_byte_provenance(studio):
    project = _project(studio)
    lora = studio.post(WINDOWS_CLAIM, json=_claim_body(project)).json()["artifact_id"]
    approval = _request_approval(studio, lora, LORA_V2_SHA, windows_evidence=_evidence()).json()
    listed = {item["approval_id"]: item for item in studio.get("/api/v1/approvals").json()}
    summary = listed[approval["approval_id"]]["scope_summary"]
    assert "asset_kind=lora" in summary
    assert "byte_provenance=WINDOWS_CLIENT_CLAIM_NOT_CORE_HASHED" in summary
    assert listed[approval["approval_id"]]["status"] == "Pending"
