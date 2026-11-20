"""Owner's explicit, SHA-fixed asset-use statements never grant GPU admission."""

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

_ROUTE = "/api/v1/studio/storypacks/owner-review/asset-use"
_SUBJECT = "pet:maotai"


def _story() -> dict:
    return {
        "schema": "picotoo.storypack.v1",
        "episode_id": "MAOTAI_RIGHTS",
        "title": "Maotai's dinner",
        "output_profile": "p0_landscape",
        "character_ref": "maotai_master_v1",
        "scene_ref": "backyard_v1",
        "style_ref": "toon_style_v1",
        "story": {"goal": "Find dinner", "payoff": "The dog hears the owner"},
        "shots": [{
            "id": "S01", "action": "Look for dinner",
            "state_in": "Dog in yard", "state_out": "Dog looks at the door",
            "because": "Owner calls",
        }],
    }


def _put_asset(api: TestClient, ref: str) -> str:
    services = api.app.state.services
    stored = services.results.put_bytes(
        ("synthetic-completely-unapproved:" + ref).encode("utf-8"),
        result_type="image",
    )
    services.database.execute(
        """INSERT OR IGNORE INTO projects
           (project_id, title, project_type, source_app,
            classification, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "asset-use-fixture", "Synthetic", "pet", "test",
            "internal", "Active", "2026-11-19T00:00:00Z", "2026-11-19T00:00:00Z",
        ),
    )
    services.database.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, artifact_type, classification,
            sha256, stored_object_hash, is_original, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            ref, "asset-use-fixture", "image", "internal",
            stored.object_hash, stored.object_hash, 1,
            "2026-11-19T00:00:00Z",
        ),
    )
    return stored.object_hash


@pytest.fixture
def context(tmp_path):
    owner_token = secrets.token_urlsafe(32)
    device_token = secrets.token_urlsafe(32)
    registry = OwnerReviewRegistry(credentials=(
        OwnerCredentialConfig(
            credential_id="asset-use-fixture",
            actor_id="pet-owner-fixture",
            token_sha256=owner_token_fingerprint(owner_token),
            subject_keys=(_SUBJECT,),
            permissions=("asset_use.attest",),
            registry_revision=1,
            enabled=True,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
    ))
    settings = AppSettings(
        paths=RuntimePaths.from_root(tmp_path),
        api_token=device_token,
        owner_review_registry=registry,
    )
    app = create_app(settings)
    with TestClient(app, client=("127.0.0.1", 59100)) as api:
        objects = {
            ref: _put_asset(api, ref)
            for ref in ("maotai_master_v1", "backyard_v1", "toon_style_v1")
        }
        yield api, owner_token, device_token, objects


def _post(api, suffix, body, token, *, key=None):
    headers = {"Authorization": f"Bearer {token}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return api.post(_ROUTE + suffix, json=body, headers=headers)


def _claims(objects):
    return [
        {
            "ref": ref,
            "asset_sha256": digest,
            "basis": "self_created",
            "commercial_ai_generation": True,
            "commercial_distribution": True,
        }
        for ref, digest in sorted(objects.items())
    ]


def _preview(api, token, objects, *, pack=None, claims=None):
    body = {
        "subject_key": _SUBJECT,
        "storypack": _story() if pack is None else pack,
        "claims": _claims(objects) if claims is None else claims,
    }
    result = _post(api, "/preview", body, token)
    assert result.status_code == 200, result.text
    return body, result.json()


def _no_production(api):
    db = api.app.state.services.database
    for table in ("tasks", "production_episodes", "approvals"):
        assert db.scalar(f"SELECT COUNT(*) FROM {table}") == 0, table


def test_asset_use_attestation_replay_verify_revoke_is_only_a_claim(context):
    api, owner, device, objects = context
    body, prepared = _preview(api, owner, objects)
    assert prepared["rights_attested"] is False
    assert prepared["rights_independently_verified"] is False
    assert prepared["master_rights_approved"] is False
    assert prepared["can_queue"] is False

    commit = {
        **body, "expected_attestation_sha256": prepared["attestation_sha256"],
        "expires_seconds": 900,
    }
    first = _post(api, "/commit", commit, owner, key="maotai-asset-use-fixture-001")
    assert first.status_code == 200, first.text
    result = first.json()
    assert result["status"] == "OWNER_ASSET_USE_ATTESTED"
    assert result["rights_attested"] is True
    assert result["rights_independently_verified"] is False
    assert result["master_rights_approved"] is False
    assert result["gpu_authorized"] is False
    assert result["can_queue"] is False
    attestation_id = result["attestation_id"]
    assert _post(
        api, "/commit", commit, owner,
        key="maotai-asset-use-fixture-001",
    ).json()["attestation_id"] == attestation_id

    valid = _post(
        api, "/verify", {**body, "attestation_id": attestation_id}, owner,
    )
    assert valid.status_code == 200, valid.text
    assert valid.json()["status"] == "OWNER_ASSET_USE_CURRENT"

    # Device Bearer must not turn a local, human-attested fact into authority.
    assert _post(api, "/verify", {
        **body, "attestation_id": attestation_id,
    }, device).status_code == 403

    revoked = _post(
        api, "/revoke", {
            "subject_key": _SUBJECT, "attestation_id": attestation_id,
        }, owner,
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "REVOKED"
    assert _post(api, "/verify", {
        **body, "attestation_id": attestation_id,
    }, owner).status_code == 409
    assert _post(
        api, "/commit", commit, owner, key="maotai-asset-use-fixture-001",
    ).status_code == 409
    assert api.app.state.services.database.scalar(
        "SELECT COUNT(*) FROM audit_events"
    ) == 2
    _no_production(api)


@pytest.mark.parametrize("problem", [
    "missing", "unknown", "sha", "duplicate", "license-proof", "self-proof",
    "wrong-scope", "wrong-bool",
])
def test_attestation_requires_exact_asset_set_and_explicit_grants(context, problem):
    api, owner, _, objects = context
    claims = _claims(objects)
    if problem == "missing":
        claims.pop()
    elif problem == "unknown":
        claims[0]["ref"] = "unapproved_character"
    elif problem == "sha":
        claims[0]["asset_sha256"] = "a" * 64
    elif problem == "duplicate":
        claims.append(copy.deepcopy(claims[0]))
    elif problem == "license-proof":
        claims[0]["basis"] = "commercial_license"
    elif problem == "self-proof":
        claims[0]["evidence_sha256"] = "b" * 64
    elif problem == "wrong-scope":
        claims[0]["basis"] = "gpu.release"
    else:
        claims[0]["commercial_ai_generation"] = False
    body = {
        "subject_key": _SUBJECT, "storypack": _story(), "claims": claims,
    }
    response = _post(api, "/preview", body, owner)
    assert response.status_code in (409, 422), (problem, response.text)
    _no_production(api)
    assert api.app.state.services.database.scalar(
        "SELECT COUNT(*) FROM audit_events"
    ) == 0


def test_asset_file_change_story_change_and_idempotency_conflict_fail(context):
    api, owner, _, objects = context
    body, prepared = _preview(api, owner, objects)
    commit = {
        **body, "expected_attestation_sha256": prepared["attestation_sha256"],
        "expires_seconds": 900,
    }
    original = _post(api, "/commit", commit, owner, key="maotai-asset-use-fixture-002")
    assert original.status_code == 200, original.text
    attestation_id = original.json()["attestation_id"]
    assert _post(api, "/commit", {
        **commit, "expires_seconds": 600,
    }, owner, key="maotai-asset-use-fixture-002").status_code == 409

    changed = copy.deepcopy(_story())
    changed["shots"][0]["action"] = "Jump toward the door"
    assert _post(api, "/verify", {
        **body, "storypack": changed, "attestation_id": attestation_id,
    }, owner).status_code == 409
    assert _post(api, "/commit", {
        **commit, "storypack": changed,
    }, owner, key="maotai-asset-use-fixture-003").status_code == 409

    # Mutate managed bytes to invalidate original SHA-bound proof.
    digest = objects["maotai_master_v1"]
    object_path = api.app.state.services.settings.paths.objects_dir / digest[:2] / digest[2:]
    object_path.write_bytes(b"tampered")
    assert _post(api, "/verify", {
        **body, "attestation_id": attestation_id,
    }, owner).status_code == 409
    _no_production(api)


def test_valid_written_permission_requires_specific_evidence_digest(context):
    api, owner, _, objects = context
    claims = _claims(objects)
    claims[1]["basis"] = "written_permission"
    claims[1]["evidence_sha256"] = "c" * 64
    _, result = _preview(api, owner, objects, claims=claims)
    assert result["rights_attested"] is False
    assert result["rights_independently_verified"] is False
    _no_production(api)
