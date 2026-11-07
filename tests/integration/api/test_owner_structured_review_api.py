from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.autonomous.evidence_ledger import (
    CanonicalEvidenceCreate,
    CanonicalEvidenceLedger,
    EvidenceOrigin,
    EvidenceTrust,
)
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.creative.source import CreativeSourceFinding, NormalizedCreativeSourceSet
from picotoopet_core.creative.state_spine import canonical_sha256
from picotoopet_core.security.owner_principal import (
    OwnerCredentialConfig,
    OwnerReviewRegistry,
    owner_token_fingerprint,
)

GOAL_ID = "goal-owner-review-api"
JOB_ID = "creative-owner-review-api"
SUBJECT = "pet:synthetic-mochi"
SOURCE_DIGEST = "1" * 64
OBJECTIVE = "Create a pet-only story with 3 shots of 4 seconds each."
DEVICE_TOKEN = "synthetic-device-token-not-owner"


def _settings(tmp_path: Path, owner_token: str, *, subjects=(SUBJECT,)) -> AppSettings:
    return AppSettings(
        paths=RuntimePaths.from_root(tmp_path / "runtime"),
        api_token=DEVICE_TOKEN,
        owner_review_registry=OwnerReviewRegistry(
            credentials=(
                OwnerCredentialConfig(
                    credential_id="owner-api-test",
                    actor_id="owner-api-actor",
                    token_sha256=owner_token_fingerprint(owner_token),
                    subject_keys=subjects,
                    permissions=("owner_facts.review",),
                    registry_revision=11,
                    enabled=True,
                ),
            )
        ),
    )


def _seed(app) -> None:
    database = app.state.services.database
    now = datetime.now(UTC).isoformat()
    evidence = CanonicalEvidenceLedger(database).ingest(
        CanonicalEvidenceCreate(
            subject_key=SUBJECT,
            evidence_type="pet.owner.visible_identity",
            source="owner_attestation",
            platform="private_mac_core",
            text_value="A synthetic legacy statement that must never become typed taxonomy.",
            value={"claim_kind": "visible_identity"},
            trust_level=EvidenceTrust.D,
            confidence=0.8,
            captured_at=datetime.now(UTC),
            provenance={"owner_reviewed": True, "photo_bytes_verified": False},
            origin_kind=EvidenceOrigin.MANUAL,
            origin_ref="owner-review-api-legacy-evidence",
        )
    )
    source = NormalizedCreativeSourceSet(
        project_key=f"goal-{GOAL_ID}",
        result_package_ids=[],
        result_digests=[],
        findings=[
            CreativeSourceFinding(
                source_finding_ref="synthetic:finding:1",
                result_package_id="goal-synthesis",
                result_digest="2" * 64,
                work_package_id="goal-synthesis",
                finding_rank=1,
                finding_digest="3" * 64,
                finding={"rank": 1, "evidence_ids": [evidence.evidence_id]},
                evidence_ids=[evidence.evidence_id],
            )
        ],
        evidence_ids=[evidence.evidence_id],
        source_set_digest=SOURCE_DIGEST,
    )
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO autonomous_goals("
            "goal_id,parent_goal_id,workflow_id,origin,intent_type,priority_class,objective,"
            "constraints_json,budget_class,pinned,score,status,idempotency_key,created_at,updated_at"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                GOAL_ID,
                None,
                None,
                "human",
                "video.creative",
                "P1",
                OBJECTIVE,
                json.dumps(
                    {"local_video_preferred": True, "owner_subject_key": SUBJECT},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "local-first",
                0,
                None,
                "Ready",
                "owner-review-api-goal",
                now,
                now,
            ),
        )
        connection.execute(
            "INSERT INTO creative_jobs("
            "creative_job_id,project_key,creative_profile,creative_objective,objective_digest,"
            "source_set_digest,status,current_stage,creative_package_id,deep_ai_handoff_id,"
            "failure_code,error_message,idempotency_key,created_at,updated_at,finished_at"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                JOB_ID,
                f"goal-{GOAL_ID}",
                "creative.content_plan.v2",
                OBJECTIVE,
                canonical_sha256({"objective": OBJECTIVE}),
                SOURCE_DIGEST,
                "Queued",
                None,
                None,
                None,
                None,
                None,
                "owner-review-api-job",
                now,
                now,
                None,
            ),
        )
        connection.execute(
            "INSERT INTO creative_goal_source_sets("
            "creative_job_id,goal_id,discovery_result_hash,synthesis_result_hash,"
            "source_set_digest,source_set_json,created_at) VALUES (?,?,?,?,?,?,?)",
            (JOB_ID, GOAL_ID, "4" * 64, "5" * 64, SOURCE_DIGEST, source.model_dump_json(), now),
        )


def _decisions() -> list[dict[str, object]]:
    values: dict[str, object] = {
        "subject_lock.subject_id": "mochi",
        "subject_lock.species": "cat",
        "subject_lock.breed_or_type": "domestic short hair",
        "subject_lock.coat_or_appearance": "white short coat with amber eyes",
        "subject_lock.distinguishing_marks": ["amber eyes", "teal scarf"],
        "pose_lock.body_pose": "seated upright with all four paws supported",
        "pose_lock.head_direction": "head facing forward",
        "pose_lock.support_surface": "cream cushion on a low wooden bench",
        "scene_lock.environment": "quiet reading nook beside one window",
        "scene_lock.lighting": "soft daylight from camera left",
        "scene_lock.temporary_accessories": ["teal scarf"],
        "camera_lock.allowed_framings": ["locked medium shot", "locked close-up"],
        "allowed_events": ["BLINK_AND_REOPEN", "SUBTLE_BREATHING"],
    }
    return [
        {"field_path": path, "decision": "CORRECT", "corrected_value": value}
        for path, value in values.items()
    ]


def test_owner_review_api_enforces_401_403_and_goal_scope(tmp_path: Path) -> None:
    owner_token = secrets.token_urlsafe(32)
    app = create_app(_settings(tmp_path, owner_token))
    _seed(app)
    with TestClient(app, client=("127.0.0.1", 51111)) as client:
        path = f"/api/v1/owner-structured-reviews/goals/{GOAL_ID}/proposal"
        assert client.get(path).status_code == 401
        device = client.get(path, headers={"Authorization": f"Bearer {DEVICE_TOKEN}"})
        assert device.status_code == 403
        assert device.json()["error"]["code"] == "OWNER_REVIEW_DEVICE_TOKEN_FORBIDDEN"

    wrong_scope_app = create_app(
        _settings(tmp_path / "other", owner_token, subjects=("pet:other",))
    )
    _seed(wrong_scope_app)
    with TestClient(wrong_scope_app, client=("127.0.0.1", 51112)) as client:
        forbidden = client.get(
            f"/api/v1/owner-structured-reviews/goals/{GOAL_ID}/proposal",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert forbidden.status_code == 403
        assert forbidden.json()["error"]["code"] == "OWNER_REVIEW_SCOPE_FORBIDDEN"


def test_owner_review_api_proposal_preview_commit_and_replay(tmp_path: Path) -> None:
    owner_token = secrets.token_urlsafe(32)
    app = create_app(_settings(tmp_path, owner_token))
    _seed(app)
    headers = {"Authorization": f"Bearer {owner_token}"}
    with TestClient(app, client=("127.0.0.1", 51113)) as client:
        proposal_response = client.get(
            f"/api/v1/owner-structured-reviews/goals/{GOAL_ID}/proposal", headers=headers
        )
        assert proposal_response.status_code == 200
        proposal = proposal_response.json()
        assert proposal["fields"]["subject_lock.species"]["status"] == "UNKNOWN"
        assert "synthetic legacy statement" not in proposal_response.text.lower()

        preview_body = {
            "goal_id": GOAL_ID,
            "review_actor_id": proposal["review_actor_id"],
            "proposal_digest": proposal["proposal_digest"],
            "decisions": _decisions(),
        }
        before = app.state.services.database.scalar("SELECT COUNT(*) FROM canonical_evidence")
        preview_response = client.post(
            "/api/v1/owner-structured-reviews/preview", headers=headers, json=preview_body
        )
        assert preview_response.status_code == 200
        preview = preview_response.json()
        assert preview["outcome"] == "READY"
        assert preview["model_calls"] == 0
        assert (
            app.state.services.database.scalar("SELECT COUNT(*) FROM canonical_evidence") == before
        )

        commit_body = {
            "preview_request": preview_body,
            "source_revision_digest": preview["source_revision_digest"],
            "review_digest": preview["review_digest"],
            "preview_digest": preview["preview_digest"],
        }
        commit_headers = {**headers, "Idempotency-Key": "owner-review-api-commit"}
        first = client.post(
            "/api/v1/owner-structured-reviews/commit",
            headers=commit_headers,
            json=commit_body,
        )
        replay = client.post(
            "/api/v1/owner-structured-reviews/commit",
            headers=commit_headers,
            json=commit_body,
        )
        assert first.status_code == 201
        assert replay.status_code == 201
        assert first.json() == replay.json()

        commit_body["preview_digest"] = "f" * 64
        conflict = client.post(
            "/api/v1/owner-structured-reviews/commit",
            headers=commit_headers,
            json=commit_body,
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "OWNER_REVIEW_IDEMPOTENCY_CONFLICT"


def test_owner_review_api_404_409_and_422_are_distinct(tmp_path: Path) -> None:
    owner_token = secrets.token_urlsafe(32)
    app = create_app(_settings(tmp_path, owner_token))
    _seed(app)
    headers = {"Authorization": f"Bearer {owner_token}"}
    with TestClient(app, client=("127.0.0.1", 51114)) as client:
        missing = client.get(
            "/api/v1/owner-structured-reviews/goals/missing/proposal", headers=headers
        )
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "OWNER_REVIEW_GOAL_SOURCE_NOT_FOUND"

        proposal = client.get(
            f"/api/v1/owner-structured-reviews/goals/{GOAL_ID}/proposal", headers=headers
        ).json()
        stale = client.post(
            "/api/v1/owner-structured-reviews/preview",
            headers=headers,
            json={
                "goal_id": GOAL_ID,
                "review_actor_id": proposal["review_actor_id"],
                "proposal_digest": "f" * 64,
                "decisions": _decisions(),
            },
        )
        assert stale.status_code == 409
        poisoned = client.post(
            "/api/v1/owner-structured-reviews/preview",
            headers=headers,
            json={
                "goal_id": GOAL_ID,
                "review_actor_id": proposal["review_actor_id"],
                "proposal_digest": proposal["proposal_digest"],
                "decisions": [
                    {
                        "field_path": "subject_lock.__dict__",
                        "decision": "CORRECT",
                        "corrected_value": "poison",
                    }
                ],
            },
        )
        assert poisoned.status_code == 422
        assert poisoned.json()["error"]["code"] == "VALIDATION_ERROR"


def test_owner_review_openapi_has_frozen_paths_and_examples(tmp_path: Path) -> None:
    owner_token = secrets.token_urlsafe(32)
    app = create_app(_settings(tmp_path, owner_token))
    document = app.openapi()
    paths = document["paths"]

    assert "/api/v1/owner-structured-reviews/goals/{goal_id}/proposal" in paths
    assert "/api/v1/owner-structured-reviews/preview" in paths
    assert "/api/v1/owner-structured-reviews/commit" in paths
    preview_schema = document["components"]["schemas"]["OwnerStructuredReviewPreviewRequest"]
    commit_schema = document["components"]["schemas"]["OwnerStructuredReviewCommitRequest"]
    assert preview_schema["additionalProperties"] is False
    assert commit_schema["additionalProperties"] is False
    assert preview_schema["examples"]
    assert commit_schema["examples"]
