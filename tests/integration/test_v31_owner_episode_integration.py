"""V3.1 integration: exact StoryPack owner review + schema-complete Episode.

Synthetic managed bytes only. The two reviews must NOT become GPU authority.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.security.owner_principal import (
    OwnerCredentialConfig,
    OwnerReviewRegistry,
    owner_token_fingerprint,
)

_STUDIO = "/api/v1/studio/storypacks"
_SUBJECT = "pet:maotai"


def _pack() -> dict:
    return {
        "schema": "picotoo.storypack.v1",
        "episode_id": "maotai_three_shots",
        "title": "Maotai hears dinner",
        "output_profile": "p0_landscape",
        "character_ref": "maotai_master_v1",
        "supporting_character_refs": ["owner_master_v1"],
        "scene_ref": "backyard_v1",
        "additional_scene_refs": ["front_door_v1"],
        "style_ref": "toon_style_v1",
        "story": {"goal": "Hear a call", "payoff": "Reach dinner"},
        "shots": [
            {
                "id": "S01",
                "action": "Play with red ball",
                "state_in": "Dog on grass",
                "state_out": "Dog holding ball",
                "because": "Introduce dog and prop",
            },
            {
                "id": "S02",
                "action": "Look toward the door",
                "state_in": "Dog holding ball",
                "state_out": "Dog facing door",
                "because": "Hear owner's call",
                "depends_on": ["S01"],
                "handoff": "continuous",
            },
            {
                "id": "S03",
                "action": "Arrive at dinner",
                "state_in": "Dog facing door",
                "state_out": "Dog at doorway",
                "because": "Complete story",
                "depends_on": ["S02"],
                "handoff": "scene_change",
                "scene_ref": "front_door_v1",
                "cast_refs": ["maotai_master_v1", "owner_master_v1"],
            },
        ],
    }


def _completion() -> dict:
    return {
        "edit": {"loudness_lufs": -14.0},
        "shots": [
            {
                "shot_id": shot_id,
                "emotion": "curious",
                "camera": {"move": "locked-off", "lens": 35.0, "speed": 1.0},
                "first_frame": {
                    "refs": [f"synthetic-unapproved-{index}.png"],
                    "prompt": f"Unit test still for shot {shot_id}",
                },
                "video": {
                    "prompt": f"Shot {shot_id}: one controlled action",
                    "negative": "flicker, identity drift",
                    "seeds": [1000 + index, 2000 + index],
                },
                "audio": {"vocal_from": "none", "foley": []},
                "transition_out": {"type": "cut", "offset_s": 0.0},
            }
            for index, shot_id in enumerate(("S01", "S02", "S03"))
        ],
    }


def _register(client: TestClient, ref: str) -> None:
    services = client.app.state.services
    stored = services.results.put_bytes(
        ("synthetic-master-not-real:" + ref).encode("utf-8"),
        result_type="image",
    )
    services.database.execute(
        """INSERT OR IGNORE INTO projects (
           project_id, title, project_type, source_app, classification,
           status, created_at, updated_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "fixture-v31", "Synthetic", "pet", "unit-test", "internal",
            "Active", "2026-11-19T00:00:00Z", "2026-11-19T00:00:00Z",
        ),
    )
    services.database.execute(
        """INSERT INTO artifacts (
           artifact_id, project_id, artifact_type, classification,
           sha256, stored_object_hash, is_original, created_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            ref, "fixture-v31", "image", "internal",
            stored.object_hash, stored.object_hash, 1, "2026-11-19T00:00:00Z",
        ),
    )


def _auth(token: str, *, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


def test_v31_full_bridge_reuses_exact_subject_but_does_not_admit_gpu(tmp_path) -> None:
    # 设备与 Owner 必须使用两种凭据，且 Owner 只接受直接 loopback 来源。
    device_token = secrets.token_urlsafe(32)
    owner_token = secrets.token_urlsafe(32)
    registry = OwnerReviewRegistry(
        credentials=(
            OwnerCredentialConfig(
                credential_id="synthetic-owner",
                actor_id="owner-review-fixture",
                token_sha256=owner_token_fingerprint(owner_token),
                subject_keys=(_SUBJECT,),
                permissions=("storypack.review",),
                registry_revision=1,
                enabled=True,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            ),
        ),
    )
    settings = AppSettings(
        paths=RuntimePaths.from_root(tmp_path),
        api_token=device_token,
        owner_review_registry=registry,
    )
    app = create_app(settings)
    with TestClient(app, client=("127.0.0.1", 59100)) as client:
        for ref in (
            "maotai_master_v1", "owner_master_v1",
            "backyard_v1", "front_door_v1", "toon_style_v1",
        ):
            _register(client, ref)
        pack = _pack()

        # 设备只能预览，不得把设备 Bearer 当作主人审核。
        preview = client.post(
            _STUDIO + "/preview", json=pack, headers=_auth(device_token),
        )
        assert preview.status_code == 200, preview.text
        prepared = preview.json()
        subject = prepared["owner_review_subject"]["subject_sha256"]
        story_sha = prepared["storypack_sha256"]
        assert prepared["owner_review_subject"]["owner_approved"] is False
        assert subject
        denied = client.post(
            _STUDIO + "/owner-review/preview",
            json={"subject_key": _SUBJECT, "storypack": pack},
            headers=_auth(device_token),
        )
        assert denied.status_code == 403

        # 独立 Owner 预览必须重复核验实际文件，并与设备草稿锁定同一版本。
        owner_preview = client.post(
            _STUDIO + "/owner-review/preview",
            json={"subject_key": _SUBJECT, "storypack": pack},
            headers=_auth(owner_token),
        )
        assert owner_preview.status_code == 200, owner_preview.text
        assert owner_preview.json()["review"]["subject_sha256"] == subject
        assert owner_preview.json()["storypack_sha256"] == story_sha

        decision = client.post(
            _STUDIO + "/owner-review/commit",
            json={
                "subject_key": _SUBJECT, "storypack": pack,
                "expected_subject_sha256": subject, "expires_seconds": 900,
            },
            headers=_auth(owner_token, key="v31-integration-three-shot-001"),
        )
        assert decision.status_code == 200, decision.text
        receipt = decision.json()
        assert receipt["status"] == "STORYBOARD_ONLY_REVIEWED"
        assert receipt["master_rights_approved"] is False
        assert receipt["gpu_authorized"] is False

        # 影片参数已满足 Episode schema，且候选仍只能作为不可信预览。
        candidate = client.post(
            _STUDIO + "/episode-candidate/preview",
            json={
                "storypack": pack,
                "storypack_sha256": story_sha,
                "completion": _completion(),
            },
            headers=_auth(device_token),
        )
        assert candidate.status_code == 200, candidate.text
        result = candidate.json()
        assert result["source_storypack_sha256"] == story_sha
        assert result["status"] == "EPISODE_CONTRACT_VALID_UNTRUSTED"
        assert result["budget_preview"]["allowed"] is True
        assert result["budget_preview"]["gpu_authorized"] is False
        assert result["episode"]["target_seconds"] == 12.0
        assert result["episode"]["edit"]["size"] == [832, 480]
        assert result["episode"]["edit"]["fps"] == 24.0
        assert result["owner_approved"] is False
        assert result["can_queue"] is False
        assert result["can_generate"] is False

        # 撤销主体审核后，同一集的参数预览仍然不能成为隐式授权。
        revoked = client.post(
            _STUDIO + "/owner-review/revoke",
            json={"subject_key": _SUBJECT, "review_id": receipt["review_id"]},
            headers=_auth(owner_token),
        )
        assert revoked.status_code == 200, revoked.text
        invalid = client.post(
            _STUDIO + "/owner-review/verify",
            json={
                "subject_key": _SUBJECT, "storypack": pack,
                "review_id": receipt["review_id"],
            },
            headers=_auth(owner_token),
        )
        assert invalid.status_code == 409

        # 只有分镜审核/撤销写入既有审计表，没有任何实际生产或批次。
        database = app.state.services.database
        for table in ("tasks", "production_episodes", "approvals"):
            assert database.scalar(f"SELECT COUNT(*) FROM {table}") == 0, table
        assert database.scalar("SELECT COUNT(*) FROM audit_events") == 2
