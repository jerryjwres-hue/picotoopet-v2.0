"""Combined real HTTP preflight always blocks production until independent gates exist."""

from __future__ import annotations

import copy
import secrets
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.security.owner_principal import (
    OwnerCredentialConfig,
    OwnerReviewRegistry,
    owner_token_fingerprint,
)

_ROOT = "/api/v1/studio/storypacks/owner-review"
_SUBJECT = "pet:maotai"


def _pack() -> dict:
    return {
        "schema": "picotoo.storypack.v1",
        "episode_id": "MAOTAI_READINESS",
        "title": "Maotai dinner",
        "output_profile": "p0_landscape",
        "character_ref": "maotai_master_v1",
        "scene_ref": "backyard_v1",
        "style_ref": "toon_style_v1",
        "story": {"goal": "Find dinner", "payoff": "Look to the door"},
        "shots": [
            {
                "id": "S01", "action": "Fetch the ball",
                "state_in": "Dog on grass", "state_out": "Dog holding ball",
                "because": "Build anticipation",
            },
            {
                "id": "S02", "action": "Turn to doorway",
                "state_in": "Dog holding ball", "state_out": "Dog looking at door",
                "because": "Owner calls", "depends_on": ["S01"],
                "handoff": "continuous",
            },
        ],
    }


def _complete() -> dict:
    return {
        "edit": {"loudness_lufs": -14.0},
        "shots": [
            {
                "shot_id": ident,
                "emotion": "curious",
                "camera": {"move": "locked-off", "lens": 35.0, "speed": 1.0},
                "first_frame": {
                    "refs": [f"unapproved-first-frame-{index}.png"],
                    "prompt": "Synthetic image, not owner-approved",
                },
                "video": {
                    "prompt": f"One motion for {ident}",
                    "negative": "flicker",
                    "seeds": [100 + index],
                },
                "audio": {"vocal_from": "none", "foley": []},
                "transition_out": {"type": "cut", "offset_s": 0.0},
            }
            for index, ident in enumerate(("S01", "S02"))
        ],
    }


@pytest.fixture
def context(tmp_path):
    owner = secrets.token_urlsafe(32)
    device = secrets.token_urlsafe(32)
    registry = OwnerReviewRegistry(credentials=(
        OwnerCredentialConfig(
            credential_id="readiness-owner",
            actor_id="owner-operator",
            token_sha256=owner_token_fingerprint(owner),
            subject_keys=(_SUBJECT,),
            permissions=("storypack.review", "asset_use.attest"),
            registry_revision=1, enabled=True,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
    ))
    app = create_app(AppSettings(
        paths=RuntimePaths.from_root(tmp_path), api_token=device,
        owner_review_registry=registry,
    ))
    with TestClient(app, client=("127.0.0.1", 59100)) as client:
        svc = app.state.services
        objects = {}
        svc.database.execute(
            """INSERT INTO projects
               (project_id,title,project_type,source_app,classification,status,
                created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)""",
            ("ready-test", "Synthetic", "pet", "test", "internal",
             "Active", "2026-11-19T00:00:00Z", "2026-11-19T00:00:00Z"),
        )
        for ref in ("maotai_master_v1", "backyard_v1", "toon_style_v1"):
            stored = svc.results.put_bytes(
                ("synthetic-dummy:" + ref).encode("utf-8"), result_type="image"
            )
            objects[ref] = stored.object_hash
            svc.database.execute(
                """INSERT INTO artifacts (
                   artifact_id,project_id,artifact_type,classification,
                   sha256,stored_object_hash,is_original,created_at
                   ) VALUES (?,?,?,?,?,?,?,?)""",
                (ref, "ready-test", "image", "internal", stored.object_hash,
                 stored.object_hash, 1, "2026-11-19T00:00:00Z"),
            )
        yield client, owner, device, objects


def _call(client, suffix, data, token, *, key=None):
    headers = {"Authorization": f"Bearer {token}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return client.post(_ROOT + suffix, json=data, headers=headers)


def _create_reviewed_candidate(client, owner, objects):
    pack = _pack()
    base = {"subject_key": _SUBJECT, "storypack": pack}
    preview = _call(client, "/preview", base, owner)
    assert preview.status_code == 200, preview.text
    subject = preview.json()
    commit = _call(client, "/commit", {
        **base,
        "expected_subject_sha256": subject["review"]["subject_sha256"],
        "expires_seconds": 900,
    }, owner, key="readiness-storyboard-001")
    assert commit.status_code == 200, commit.text

    claims = [
        {
            "ref": ref, "asset_sha256": digest, "basis": "self_created",
            "commercial_ai_generation": True, "commercial_distribution": True,
        }
        for ref, digest in sorted(objects.items())
    ]
    proof = _call(client, "/asset-use/preview", {**base, "claims": claims}, owner)
    assert proof.status_code == 200, proof.text
    attestation = _call(client, "/asset-use/commit", {
        **base, "claims": claims,
        "expected_attestation_sha256": proof.json()["attestation_sha256"],
        "expires_seconds": 900,
    }, owner, key="readiness-asset-use-001")
    assert attestation.status_code == 200, attestation.text
    return {
        **base,
        "claims": claims,
        "storyboard_review_id": commit.json()["review_id"],
        "attestation_id": attestation.json()["attestation_id"],
        "storypack_sha256": subject["storypack_sha256"],
        "completion": _complete(),
    }


def _assert_no_production(client):
    db = client.app.state.services.database
    for table in ("tasks", "production_episodes", "approvals"):
        assert db.scalar(f"SELECT COUNT(*) FROM {table}") == 0, table


def test_valid_owner_proofs_and_complete_episode_still_cannot_create_jobs(context):
    client, owner, device, objects = context
    payload = _create_reviewed_candidate(client, owner, objects)
    before = client.app.state.services.database.scalar(
        "SELECT COUNT(*) FROM audit_events"
    )
    response = _call(client, "/production-readiness", payload, owner)
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["status"] == "BLOCKED_PRODUCTION_ADMISSION"
    assert report["checks"]["storyboard_review_current"] is True
    assert report["checks"]["asset_use_attestation_current"] is True
    assert report["checks"]["episode_contract_valid"] is True
    assert report["checks"]["episode_budget_allowed"] is True
    assert report["candidate_episode_sha256"]
    assert report["budget_preview"]["initial_video_takes"] == 2
    assert report["checks"]["master_rights_independently_verified"] is False
    assert "MASTER_RIGHTS_NOT_VERIFIED" in report["blocking_reasons"]
    assert "GPU_HOLD_NOT_RELEASED" in report["blocking_reasons"]
    assert report["can_queue"] is False
    assert report["can_generate"] is False
    assert report["read_only"] is True
    assert _call(client, "/production-readiness", payload, device).status_code == 403
    assert _call(client, "/production-readiness", payload, owner).json() == report
    assert client.app.state.services.database.scalar(
        "SELECT COUNT(*) FROM audit_events"
    ) == before
    _assert_no_production(client)


def test_revoke_or_mutate_evidence_surfaces_blockers_without_new_tasks(context):
    client, owner, _, objects = context
    payload = _create_reviewed_candidate(client, owner, objects)
    revoked = _call(client, "/revoke", {
        "subject_key": _SUBJECT,
        "review_id": payload["storyboard_review_id"],
    }, owner)
    assert revoked.status_code == 200, revoked.text
    invalid = _call(client, "/production-readiness", payload, owner)
    assert invalid.status_code == 200, invalid.text
    assert invalid.json()["checks"]["storyboard_review_current"] is False
    assert "OWNER_STORYBOARD_REVIEW_REVOKED" in invalid.json()["blocking_reasons"]

    # Replacing bytes invalidates the separate asset-use assertion as well.
    digest = objects["maotai_master_v1"]
    root = client.app.state.services.settings.paths.objects_dir
    (root / digest[:2] / digest[2:]).write_bytes(b"tampered")
    stale = _call(client, "/production-readiness", payload, owner)
    assert stale.status_code == 200, stale.text
    assert stale.json()["checks"]["asset_use_attestation_current"] is False
    assert stale.json()["checks"]["storyboard_review_current"] is False
    _assert_no_production(client)


def test_invalid_episode_or_budget_is_displayed_but_never_queued(context):
    client, owner, _, objects = context
    payload = _create_reviewed_candidate(client, owner, objects)
    bad = copy.deepcopy(payload)
    bad["completion"]["shots"][1]["shot_id"] = "S99"
    response = _call(client, "/production-readiness", bad, owner)
    assert response.status_code == 200, response.text
    assert response.json()["checks"]["episode_contract_valid"] is False
    assert "EPISODE_SHOT_ORDER_OR_ID_DRIFT" in response.json()["blocking_reasons"]

    budget = copy.deepcopy(payload)
    budget["completion"]["shots"][0]["video"]["seeds"] = list(range(9))
    result = _call(client, "/production-readiness", budget, owner)
    assert result.status_code == 200, result.text
    assert result.json()["checks"]["episode_contract_valid"] is True
    assert result.json()["checks"]["episode_budget_allowed"] is False
    assert "EPISODE_BUDGET_EXCEEDED" in result.json()["blocking_reasons"]
    _assert_no_production(client)



def test_managed_frame_ids_bind_sha_but_windows_worker_remains_unverified(context):
    client, owner, _, objects = context
    payload = _create_reviewed_candidate(client, owner, objects)

    # 使用当前 StoryPack 的角色与场景 ID，而非凭空猜测的 Windows 路径。
    payload["completion"]["shots"][0]["first_frame"]["refs"] = [
        "maotai_master_v1", "backyard_v1",
    ]
    payload["completion"]["shots"][1]["first_frame"]["refs"] = [
        "maotai_master_v1",
    ]
    result = _call(client, "/production-readiness", payload, owner)
    assert result.status_code == 200, result.text
    report = result.json()
    refs = report["frame_reference_preview"]

    assert report["checks"]["first_frame_mac_content_bound"] is True
    assert report["checks"]["first_frame_worker_local_verified"] is False
    assert refs["status"] == "MAC_CONTENT_BOUND_WORKER_STAGING_REQUIRED"
    assert refs["source_bindings_sha256"]
    assert {
        (row["shot_id"], row["role"], row["asset_ref"], row["managed_sha256"])
        for row in refs["bindings"]
    } == {
        ("S01", "first", "maotai_master_v1", objects["maotai_master_v1"]),
        ("S01", "first", "backyard_v1", objects["backyard_v1"]),
        ("S02", "first", "maotai_master_v1", objects["maotai_master_v1"]),
    }
    assert "FRAME_WORKER_STAGING_AND_HASH_REQUIRED" in report["blocking_reasons"]
    assert report["can_queue"] is False
    assert report["can_generate"] is False
    assert _call(client, "/production-readiness", payload, owner).json() == report
    _assert_no_production(client)


@pytest.mark.parametrize("invalid_ref,expected_error", [
    ("C:\\\\private\\\\maotai.png", "FRAME_PATH_NOT_A_MANAGED_ID"),
    ("../../private/maotai.png", "FRAME_PATH_NOT_A_MANAGED_ID"),
    ("unknown_reference.png", "FRAME_REFERENCE_UNDECLARED_FOR_SHOT"),
])
def test_untrusted_first_frame_strings_never_become_worker_file_paths(
    context, invalid_ref, expected_error,
):
    client, owner, _, objects = context
    payload = _create_reviewed_candidate(client, owner, objects)
    payload["completion"]["shots"][0]["first_frame"]["refs"] = [invalid_ref]
    report = _call(client, "/production-readiness", payload, owner)
    assert report.status_code == 200, report.text
    parsed = report.json()
    assert parsed["checks"]["first_frame_mac_content_bound"] is False
    assert any(
        reason.startswith(expected_error)
        for reason in parsed["blocking_reasons"]
    )
    assert parsed["can_queue"] is False
    _assert_no_production(client)


def test_duplicate_frame_ref_and_stale_master_bytes_cannot_pass(context):
    client, owner, _, objects = context
    payload = _create_reviewed_candidate(client, owner, objects)
    payload["completion"]["shots"][0]["first_frame"]["refs"] = [
        "maotai_master_v1", "maotai_master_v1",
    ]
    duplicate = _call(client, "/production-readiness", payload, owner)
    assert duplicate.status_code == 200, duplicate.text
    assert any(
        reason.startswith("FRAME_DUPLICATE_REFERENCE")
        for reason in duplicate.json()["blocking_reasons"]
    )

    payload["completion"]["shots"][0]["first_frame"]["refs"] = ["maotai_master_v1"]
    payload["completion"]["shots"][1]["first_frame"]["refs"] = ["maotai_master_v1"]
    digest = objects["maotai_master_v1"]
    root = client.app.state.services.settings.paths.objects_dir
    (root / digest[:2] / digest[2:]).write_bytes(b"tampered managed bytes")
    stale = _call(client, "/production-readiness", payload, owner)
    assert stale.status_code == 200, stale.text
    report = stale.json()
    assert report["checks"]["first_frame_mac_content_bound"] is False
    assert "FRAME_MASTER_CONTENT_UNVERIFIED" in report["blocking_reasons"]
    assert report["can_generate"] is False
    _assert_no_production(client)
