"""Authenticated dynamic StoryPack review tests with synthetic managed assets only."""

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

_ENDPOINT = "/api/v1/studio/storypacks/owner-review"
_SUBJECT = "pet:maotai"


def _pack() -> dict:
    return {
        "schema": "picotoo.storypack.v1",
        "episode_id": "maotai_ep02",
        "title": "Dinner adventure",
        "output_profile": "p0_landscape",
        "character_ref": "maotai_master_v1",
        "scene_ref": "backyard_v1",
        "additional_scene_refs": ["front_door_v1"],
        "style_ref": "toon_style_v1",
        "story": {"goal": "Find dinner", "payoff": "Go home"},
        "shots": [
            {
                "id": "S01", "action": "Run", "state_in": "Garden",
                "state_out": "Door", "because": "Hungry",
            },
            {
                "id": "S02", "action": "Arrive", "state_in": "Door",
                "state_out": "Home", "because": "Dinner",
                "scene_ref": "front_door_v1", "depends_on": ["S01"],
                "handoff": "scene_change",
            },
        ],
    }


def _register(api: TestClient, ref: str) -> None:
    services = api.app.state.services
    stored = services.results.put_bytes(("synthetic:" + ref).encode(), result_type="image")
    services.database.execute(
        """INSERT OR IGNORE INTO projects
           (project_id,title,project_type,source_app,classification,status,created_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        ("owner-review-project", "Fixture", "pet", "test", "internal", "Active",
         "2026-11-19T00:00:00Z", "2026-11-19T00:00:00Z"),
    )
    services.database.execute(
        """INSERT INTO artifacts
           (artifact_id,project_id,artifact_type,classification,sha256,stored_object_hash,
            is_original,created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (ref, "owner-review-project", "image", "internal",
         stored.object_hash, stored.object_hash, 1, "2026-11-19T00:00:00Z"),
    )


@pytest.fixture
def api(tmp_path):
    device_token = secrets.token_urlsafe(32)
    owner_token = secrets.token_urlsafe(32)
    registry = OwnerReviewRegistry(credentials=(
        OwnerCredentialConfig(
            credential_id="local-maotai-owner",
            actor_id="review-actor",
            token_sha256=owner_token_fingerprint(owner_token),
            subject_keys=(_SUBJECT,),
            permissions=("storypack.review",),
            registry_revision=1, enabled=True,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
    ))
    settings = AppSettings(
        paths=RuntimePaths.from_root(tmp_path),
        api_token=device_token, owner_review_registry=registry,
    )
    app = create_app(settings)
    # TestClient explicitly simulates direct loopback; proxy headers remain forbidden.
    with TestClient(app, client=("127.0.0.1", 59100)) as client:
        for ref in ("maotai_master_v1", "backyard_v1", "front_door_v1", "toon_style_v1"):
            _register(client, ref)
        yield client, owner_token, device_token


def _call(api, path: str, body: dict, token: str, *, key: str | None = None):
    headers = {"Authorization": f"Bearer {token}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return api.post(_ENDPOINT + path, json=body, headers=headers)


def _subject(api, owner_token, pack=None):
    payload = {"subject_key": _SUBJECT, "storypack": pack or _pack()}
    response = _call(api, "/preview", payload, owner_token)
    assert response.status_code == 200, response.text
    return response.json()["review"]["subject_sha256"]


def test_owner_storyboard_exact_commit_replay_verify_revoke(api):
    client, token, device_token = api
    before_tasks = client.app.state.services.database.scalar("SELECT COUNT(*) FROM tasks")
    subject = _subject(client, token)
    payload = {
        "subject_key": _SUBJECT, "storypack": _pack(),
        "expected_subject_sha256": subject, "expires_seconds": 900,
    }
    first = _call(client, "/commit", payload, token, key="owner-review-maotai-001")
    assert first.status_code == 200, first.text
    result = first.json()
    assert result["status"] == "STORYBOARD_ONLY_REVIEWED"
    assert result["master_rights_approved"] is False
    assert result["gpu_authorized"] is False
    assert result["can_queue"] is False
    repeated = _call(client, "/commit", payload, token, key="owner-review-maotai-001")
    assert repeated.status_code == 200
    assert repeated.json()["review_id"] == result["review_id"]
    verified = _call(client, "/verify", {
        "subject_key": _SUBJECT, "storypack": _pack(), "review_id": result["review_id"],
    }, token)
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "STORYBOARD_ONLY_CURRENT"
    revoked = _call(client, "/revoke", {
        "subject_key": _SUBJECT, "review_id": result["review_id"],
    }, token)
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "REVOKED"
    assert _call(client, "/verify", {
        "subject_key": _SUBJECT, "storypack": _pack(), "review_id": result["review_id"],
    }, token).status_code == 409
    assert _call(client, "/commit", payload, token, key="owner-review-maotai-001").status_code == 409
    assert client.app.state.services.database.scalar("SELECT COUNT(*) FROM tasks") == before_tasks
    assert client.app.state.services.database.scalar("SELECT COUNT(*) FROM production_episodes") == 0
    assert client.app.state.services.database.scalar("SELECT COUNT(*) FROM approvals") == 0


def test_changed_story_and_asset_sha_and_idempotency_fail_closed(api):
    client, token, _ = api
    subject = _subject(client, token)
    payload = {
        "subject_key": _SUBJECT, "storypack": _pack(),
        "expected_subject_sha256": subject, "expires_seconds": 900,
    }
    approved = _call(client, "/commit", payload, token, key="owner-review-maotai-002")
    assert approved.status_code == 200, approved.text
    review_id = approved.json()["review_id"]
    new_pack = copy.deepcopy(_pack())
    new_pack["shots"][0]["action"] = "Jump"
    assert _call(client, "/verify", {
        "subject_key": _SUBJECT, "storypack": new_pack, "review_id": review_id,
    }, token).status_code == 409
    assert _call(client, "/commit", {**payload, "storypack": new_pack}, token,
                 key="owner-review-maotai-003").status_code == 409
    assert _call(client, "/commit", {**payload, "expires_seconds": 600}, token,
                 key="owner-review-maotai-002").status_code == 409

    database = client.app.state.services.database
    database.execute(
        "UPDATE artifacts SET sha256=? WHERE artifact_id=?",
        ("a" * 64, "backyard_v1"),
    )
    assert _call(client, "/verify", {
        "subject_key": _SUBJECT, "storypack": _pack(), "review_id": review_id,
    }, token).status_code == 409
    assert client.app.state.services.database.scalar("SELECT COUNT(*) FROM tasks") == 0


def test_device_token_and_wrong_scope_and_proxy_are_denied(api):
    client, token, device = api
    payload = {"subject_key": _SUBJECT, "storypack": _pack()}
    assert _call(client, "/preview", payload, device).status_code == 403
    assert _call(client, "/preview", payload, "invalid-token").status_code == 401
    assert _call(client, "/preview", {
        **payload, "subject_key": "pet:unknown",
    }, token).status_code == 403
    response = client.post(
        _ENDPOINT + "/preview", json=payload,
        headers={"Authorization": f"Bearer {token}", "X-Forwarded-For": "127.0.0.1"},
    )
    assert response.status_code == 403


def test_unverified_assets_and_duplicate_story_keys_cannot_be_committed(api):
    client, token, _ = api
    database = client.app.state.services.database
    database.execute(
        "UPDATE artifacts SET stored_object_hash=NULL WHERE artifact_id=?",
        ("toon_style_v1",),
    )
    preview = _call(client, "/preview", {"subject_key": _SUBJECT, "storypack": _pack()}, token)
    assert preview.status_code == 200
    assert preview.json()["review"]["subject_sha256"] is None
    bad_commit = _call(client, "/commit", {
        "subject_key": _SUBJECT, "storypack": _pack(),
        "expected_subject_sha256": "a" * 64,
    }, token, key="owner-review-maotai-004")
    assert bad_commit.status_code == 409
    duplicated = '{"subject_key":"pet:maotai","subject_key":"pet:wrong","storypack":{}}'
    response = client.post(
        _ENDPOINT + "/preview", content=duplicated,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert database.scalar("SELECT COUNT(*) FROM audit_events") == 0
