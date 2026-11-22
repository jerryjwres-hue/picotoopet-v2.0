"""#296: V3.1 Studio preview must leave real 2.3's production authority untouched."""

from __future__ import annotations

import copy
import base64
import hashlib
import json
import secrets

import pytest
from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.autonomous.goal_service import HumanGoalRequest
from picotoopet_core.creative.director import parse_goal_directives
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths

ROUTE = "/api/v1/studio/storypacks/preview"


@pytest.fixture
def studio(tmp_path):
    """以真实 2.3 Schema-24 初始化 Core；唯一差异是使用临时沙盒数据库。"""

    token = secrets.token_hex(24)
    app = create_app(AppSettings(paths=RuntimePaths.from_root(tmp_path), api_token=token))
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        yield client


def storypack() -> dict:
    """3×4 秒《茅台》测试结构只含语义输入，不构造可执行 GPU Plan。"""

    return {
        "schema": "picotoo.storypack.v1",
        "episode_id": "maotai_dinner_pilot",
        "title": "Maotai Dinner",
        "output_profile": "p0_landscape",
        "character_ref": "maotai_master_v1",
        "scene_ref": "dinner_room_v1",
        "style_ref": "cute_3d_style_v1",
        "story": {
            "goal": "Maotai wants dinner",
            "payoff": "Maotai reaches his bowl",
        },
        "shots": [
            {
                "id": "S01",
                "action": "Maotai sees his bowl",
                "state_in": "Maotai by the door",
                "state_out": "Maotai by the bowl",
                "because": "He smells dinner",
            },
            {
                "id": "S02",
                "action": "Maotai looks at the bowl",
                "state_in": "Maotai by the bowl",
                "state_out": "Maotai is sitting",
                "because": "He is curious",
                "depends_on": ["S01"],
                "handoff": "continuous",
            },
            {
                "id": "S03",
                "action": "Maotai enjoys dinner",
                "state_in": "Maotai is sitting",
                "state_out": "Maotai is happy",
                "because": "His bowl is ready",
                "depends_on": ["S02"],
                "handoff": "continuous",
            },
        ],
    }


def _counts(client: TestClient) -> tuple[int, int, int]:
    """原有任务、审批、生产 Job 的计数构成只读性不变量。"""

    db = client.app.state.services.database
    return tuple(
        int(db.scalar(f"SELECT COUNT(*) FROM {table}") or 0)
        for table in ("tasks", "approvals", "production_jobs")
    )


def test_three_shot_preview_is_deterministic_and_never_enqueues(studio):
    before = _counts(studio)
    first = studio.post(ROUTE, json=storypack())
    assert first.status_code == 200, first.text
    data = first.json()
    assert data["validated"] is True
    assert data["shot_count"] == 3
    assert data["output"]["width"] == 832
    assert data["output"]["height"] == 480
    assert data["output"]["fps"] == 24
    # Use the canonical Wan 4n+1 frame count, not simplistic 4 × 24 = 96.
    assert data["output"]["frames_per_shot"] == 97
    assert data["output"]["planned_frames"] == 291
    assert data["output"]["planned_duration_s"] == 12
    assert data["can_queue"] is False
    assert data["production_compilation"]["executable"] is False
    intake = data["canonical_goal_intake"]
    assert intake["ready_for_user_submission"] is True
    assert intake["requires_explicit_user_action"] is True
    assert intake["storypack_sha256"] == data["storypack_sha256"]
    assert intake["goal_type"] == "video.creative"
    assert intake["depth"] == "standard"
    assert intake["local_video_preferred"] is True
    assert all(intake[key] is False for key in (
        "source_evidence_verified", "creative_package_approved",
        "production_plan_executable", "owner_approved", "gpu_post_authorized",
    ))
    # 现有 2.3 Goal 契约能真实接受提案；预览本身仍没有提交 Goal。
    _ = HumanGoalRequest.model_validate({
        "goal_type": intake["goal_type"],
        "depth": intake["depth"],
        "objective": intake["objective"],
        "local_video_preferred": intake["local_video_preferred"],
    })
    directives = parse_goal_directives(intake["objective"])
    assert directives.shot_count == 3
    assert directives.shot_seconds == 4
    assert directives.pet_only is True
    assert data["production_compilation"]["reason"] == "CANONICAL_23_PRODUCTION_BRIDGE_NOT_IMPLEMENTED"
    assert data["core23_compatibility"]["gpu_post_authorized"] is False
    assert data["owner_review_subject"]["owner_approved"] is False
    assert data["owner_review_subject"]["status"] == "BLOCKED_INCOMPLETE_EVIDENCE"
    assert data["fingerprint_plan"]["can_queue"] is False
    assert all(not item["usable_for_generation"] for item in data["asset_record_checks"])
    assert first.headers["cache-control"] == "no-store, private"

    # 同一输入不产生新任务、Lease、审批或实机 Comfy POST。
    second = studio.post(ROUTE, json=storypack())
    assert second.status_code == 200
    assert second.json()["storypack_sha256"] == data["storypack_sha256"]
    assert second.json()["fingerprint_plan"] == data["fingerprint_plan"]
    assert _counts(studio) == before


@pytest.mark.parametrize("reason", ["state", "duplicate_shot", "path", "unknown_dep", "extra_key"])
def test_invalid_storypack_cannot_escape_canonical_core(studio, reason):
    pack = copy.deepcopy(storypack())
    if reason == "state":
        pack["shots"][1]["state_in"] = "wrong continuity"
    elif reason == "duplicate_shot":
        pack["shots"][1]["id"] = "s01"
    elif reason == "path":
        pack["scene_ref"] = "../../private"
    elif reason == "unknown_dep":
        pack["shots"][1]["depends_on"] = ["S99"]
    else:
        pack["execute_shell"] = "powershell.exe"

    before = _counts(studio)
    response = studio.post(ROUTE, json=pack)
    assert response.status_code == 422
    assert _counts(studio) == before


def test_untrusted_request_never_reads_studio_preview(studio):
    before = _counts(studio)
    denied = studio.post(
        ROUTE, json=storypack(), headers={"Authorization": "Bearer unauthorized"}
    )
    assert denied.status_code == 401
    assert _counts(studio) == before


def test_duplicate_keys_and_nonfinite_json_fail_closed(studio):
    before = _counts(studio)
    for body in (
        b'{"schema":"picotoo.storypack.v1","schema":"picotoo.storypack.v1"}',
        json.dumps(storypack()).replace('"shots":', '"shots": NaN, "shots":').encode(),
    ):
        response = studio.post(
            ROUTE, content=body, headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 422
    assert _counts(studio) == before


def test_oversize_yaml_and_unsupported_content_are_denied(studio):
    before = _counts(studio)
    oversized = studio.post(
        ROUTE,
        content=b"x" * (128 * 1024 + 1),
        headers={"Content-Type": "application/json"},
    )
    assert oversized.status_code == 413
    yaml_attempt = studio.post(
        ROUTE,
        content="schema: picotoo.storypack.v1",
        headers={"Content-Type": "application/yaml"},
    )
    assert yaml_attempt.status_code == 415
    assert _counts(studio) == before


def test_changes_are_scoped_to_dependent_shots(studio):
    base = studio.post(ROUTE, json=storypack()).json()
    modified = storypack()
    modified["shots"][0]["action"] = "Maotai follows the food bowl"
    newer = studio.post(ROUTE, json=modified).json()
    assert newer["storypack_sha256"] != base["storypack_sha256"]
    old_keys = [shot["input_sha256"] for shot in base["fingerprint_plan"]["shots"]]
    new_keys = [shot["input_sha256"] for shot in newer["fingerprint_plan"]["shots"]]
    assert all(old != new for old, new in zip(old_keys, new_keys, strict=True))
    assert newer["can_queue"] is False


def test_goal_intake_blocks_oversize_and_non_p0_without_writing(studio):
    """不截断故事，也不让不合规格的草稿静默变成 Goal。"""

    before = _counts(studio)
    too_long = storypack()
    for shot in too_long["shots"]:
        shot["action"] = shot["action"] + (" 长动作" * 210)
    long_response = studio.post(ROUTE, json=too_long)
    assert long_response.status_code == 200
    long_intake = long_response.json()["canonical_goal_intake"]
    assert long_intake["ready_for_user_submission"] is False
    assert long_intake["objective"] is None
    assert "GOAL_OBJECTIVE_OVER_2000_CHARS" in long_intake["blocking_reasons"]
    assert long_response.json()["production_compilation"]["executable"] is False

    two_shots = storypack()
    two_shots["shots"] = two_shots["shots"][:2]
    two_response = studio.post(ROUTE, json=two_shots)
    assert two_response.status_code == 200
    two_intake = two_response.json()["canonical_goal_intake"]
    assert two_intake["ready_for_user_submission"] is False
    assert "P0_REQUIRES_EXACTLY_THREE_SHOTS" in two_intake["blocking_reasons"]
    assert two_intake["objective"] is None
    assert _counts(studio) == before


def test_storypack_uses_existing_human_goal_route_idempotently_without_production(studio):
    """真实 Core API：草稿→原有 Human Goal；没有另建 Production/Worker/GPU 通道。"""

    preview = studio.post(ROUTE, json=storypack())
    assert preview.status_code == 200
    intake = preview.json()["canonical_goal_intake"]
    assert intake["ready_for_user_submission"] is True

    # 这次测试模拟了 UI 的明确二次确认；预览 GET/POST 本身仍零写入。
    goal_request = {
        "goal_type": intake["goal_type"],
        "objective": intake["objective"],
        "depth": intake["depth"],
        "local_video_preferred": intake["local_video_preferred"],
    }
    key = "studio-storypack-goal-v1-" + intake["storypack_sha256"]
    db = studio.app.state.services.database
    before_prod = int(db.scalar("SELECT COUNT(*) FROM production_jobs") or 0)
    before_approvals = int(db.scalar("SELECT COUNT(*) FROM approvals") or 0)

    first = studio.post(
        "/api/v1/autonomous/goals",
        json=goal_request,
        headers={"Idempotency-Key": key},
    )
    assert first.status_code == 201, first.text
    created = first.json()
    assert created["intent_type"] == "video.creative"
    assert created["constraints"]["local_video_preferred"] is True
    assert created["constraints"]["read_only_research"] is True
    assert created["workflow_id"] is not None

    replay = studio.post(
        "/api/v1/autonomous/goals",
        json=goal_request,
        headers={"Idempotency-Key": key},
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["goal_id"] == created["goal_id"]
    assert replay.json()["workflow_id"] == created["workflow_id"]

    # Goal can research, but only the existing canonical Creative and Owner/Worker
    # gates may ever make a ProductionPlan executable or permit a GPU POST.
    assert int(db.scalar("SELECT COUNT(*) FROM production_jobs") or 0) == before_prod
    assert int(db.scalar("SELECT COUNT(*) FROM approvals") or 0) == before_approvals
    stored = studio.get(f'/api/v1/autonomous/goals/{created["goal_id"]}')
    assert stored.status_code == 200
    assert stored.json()["goal_id"] == created["goal_id"]


ASSET_ROUTE = "/api/v1/studio/assets/import"
# Real 1x1 PNG bytes used solely in temporary CPU-only integrity tests.
_ASSET_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+XgZsAAAAASUVORK5CYII="
)


def _asset_project(studio):
    response = studio.post("/api/v1/projects", json={
        "title": "Local intake fixture", "project_type": "film", "source_app": "test",
        "classification": "INTERNAL",
    })
    assert response.status_code == 201, response.text
    return response.json()["project_id"]


def _asset_headers(project_id, role, data, media="image/png"):
    return {
        "X-Picotoo-Project-Id": project_id,
        "X-Picotoo-Asset-Role": role,
        "X-Picotoo-Asset-SHA256": hashlib.sha256(data).hexdigest(),
        "X-Picotoo-Import-Confirmed": "yes",
        "Content-Type": media,
    }


def test_asset_intake_reuses_store_and_prepares_unapproved_subject(studio):
    project = _asset_project(studio)
    before = _counts(studio)
    db = studio.app.state.services.database
    refs = {}
    for role, data, media in (
        ("character", _ASSET_PNG, "image/png"),
        ("scene", _ASSET_PNG, "image/png"),
        ("style", b"Stylized local test only", "text/plain"),
    ):
        headers = _asset_headers(project, role, data, media)
        first = studio.post(ASSET_ROUTE, content=data, headers=headers)
        assert first.status_code == 201, first.text
        receipt = first.json()
        refs[f"{role}_ref"] = receipt["artifact_id"]
        assert receipt["registration"] == "CREATED"
        assert receipt["content_integrity_verified"] is True
        assert receipt["cloud_policy"] == "local_only"
        assert all(receipt[key] is False for key in (
            "is_original", "owner_approved", "master_approved", "gpu_post_authorized", "can_queue"
        ))
        replay = studio.post(ASSET_ROUTE, content=data, headers=headers)
        assert replay.status_code == 201
        assert replay.json()["artifact_id"] == receipt["artifact_id"]
        assert replay.json()["registration"] == "REPLAY"
        assert db.scalar("SELECT COUNT(*) FROM artifacts WHERE artifact_id=?",
                         (receipt["artifact_id"],)) == 1
    pack = storypack()
    pack.update(refs)
    preview = studio.post(ROUTE, json=pack)
    assert preview.status_code == 200, preview.text
    result = preview.json()
    assert all(item["managed_object_integrity"] == "CONTENT_VERIFIED_UNAPPROVED"
               and not item["usable_for_generation"] for item in result["asset_record_checks"])
    assert result["owner_review_subject"]["status"] == "REVIEW_SUBJECT_PREPARED_UNAPPROVED"
    assert result["owner_review_subject"]["owner_approved"] is False
    assert result["can_queue"] is False
    assert _counts(studio) == before


@pytest.mark.parametrize("case,expected", [
    ("auth", 401), ("confirmation", 409), ("digest", 409), ("role", 422),
    ("project", 409), ("media", 409), ("oversize", 413),
])
def test_asset_intake_rejects_invalid_requests_without_registration(studio, case, expected):
    project = _asset_project(studio)
    before = _counts(studio)
    db = studio.app.state.services.database
    data = _ASSET_PNG
    headers = _asset_headers(project, "character", data)
    if case == "auth":
        headers["Authorization"] = "Bearer invalid"
    elif case == "confirmation":
        headers["X-Picotoo-Import-Confirmed"] = "no"
    elif case == "digest":
        headers["X-Picotoo-Asset-SHA256"] = "0" * 64
    elif case == "role":
        headers["X-Picotoo-Asset-Role"] = "../private"
    elif case == "project":
        headers["X-Picotoo-Project-Id"] = "missing"
    elif case == "media":
        headers["Content-Type"] = "text/html"
    else:
        data = b"x" * (16 * 1024 * 1024 + 1)
    response = studio.post(ASSET_ROUTE, content=data, headers=headers)
    assert response.status_code == expected, response.text
    assert db.scalar("SELECT COUNT(*) FROM artifacts") == 0
    assert _counts(studio) == before


def test_asset_intake_never_repairs_tampered_object_or_follows_link(studio, tmp_path):
    project = _asset_project(studio)
    data = _ASSET_PNG
    headers = _asset_headers(project, "character", data)
    first = studio.post(ASSET_ROUTE, content=data, headers=headers)
    assert first.status_code == 201
    digest = first.json()["sha256"]
    store = studio.app.state.services.results
    target = store.objects_dir / digest[:2] / digest[2:]
    target.write_bytes(b"tampered")
    rejected = studio.post(ASSET_ROUTE, content=data, headers=headers)
    assert rejected.status_code == 409
    assert target.read_bytes() == b"tampered"

    # For the symlink case use a managed leaf pointing at a sandbox fixture.
    # Windows CI can require a privilege to create symlinks; native Mac does not.
    target.unlink()
    external = tmp_path / "protected-fixture"
    external.write_bytes(data)
    try:
        target.symlink_to(external)
    except OSError:
        pytest.skip("symlink unavailable on this test host")
    rejected = studio.post(ASSET_ROUTE, content=data, headers=headers)
    assert rejected.status_code == 409
    assert external.read_bytes() == data
    assert target.is_symlink()


SCOPED_ROUTE = "/api/v1/studio/storypacks/scoped-goal"


def _reviewed_packet(studio, subject, photo_hash, intent):
    packet = {
        "subject_key": subject,
        "photo_sha256_claim": photo_hash,
        "claims": [
            {"kind": "visible_identity", "statement": "A gray and white dog wears a green scarf."},
            {"kind": "visible_scene", "statement": "A round bowl rests on the kitchen floor."},
            {"kind": "creative_intent", "statement": intent},
        ],
    }
    preview = studio.post("/api/v1/autonomous/owner-subject-evidence/preview", json=packet)
    assert preview.status_code == 200, preview.text
    digest = preview.json()["packet_digest"]
    commit = studio.post("/api/v1/autonomous/owner-subject-evidence/commit", json={
        "packet": packet, "reviewed_digest": digest, "owner_confirmed": True,
    })
    assert commit.status_code == 201, commit.text
    assert commit.json()["production_approval_granted"] is False
    return digest


@pytest.fixture
def scoped_story(studio):
    project = _asset_project(studio)
    pack = storypack()
    for role, data, media in (
        ("character", _ASSET_PNG, "image/png"),
        ("scene", _ASSET_PNG, "image/png"),
        ("style", b"Local style test", "text/plain"),
    ):
        receipt = studio.post(ASSET_ROUTE, content=data, headers=_asset_headers(
            project, role, data, media
        ))
        assert receipt.status_code == 201, receipt.text
        pack[f"{role}_ref"] = receipt.json()["artifact_id"]

    preview = studio.post(ROUTE, json=pack)
    assert preview.status_code == 200, preview.text
    subject = preview.json()["owner_review_subject"]
    assert subject["status"] == "REVIEW_SUBJECT_PREPARED_UNAPPROVED"
    return {
        "storypack": pack,
        "project_id": project,
        "owner_subject_key": "pet:maotai",
        "confirmed_subject_sha256": subject["subject_sha256"],
        "reviewed_packet_sha256": _reviewed_packet(
            studio, "pet:maotai", hashlib.sha256(_ASSET_PNG).hexdigest(),
            "The dog intends to wait and then eat dinner.",
        ),
    }


def test_scoped_goal_pins_exact_existing_packet_and_local_workflow(studio, scoped_story):
    from picotoopet_core.autonomous.discovery import ContentDiscoveryCoordinator
    from picotoopet_core.autonomous.evidence_ledger import CanonicalEvidenceLedger
    from picotoopet_core.autonomous.local_intelligence import LocalAnalysisResult

    # 新的主人声明不应静默替换已经选择的旧声明；二者同属一个真实宠物范围。
    later = _reviewed_packet(
        studio, "pet:maotai", hashlib.sha256(_ASSET_PNG).hexdigest(),
        "The dog intends to sleep beside the kitchen doorway.",
    )
    assert later != scoped_story["reviewed_packet_sha256"]
    db = studio.app.state.services.database
    services = studio.app.state.services
    before = _counts(studio)
    headers = {"X-Picotoo-Goal-Confirmed": "yes"}
    first = studio.post(SCOPED_ROUTE, json=scoped_story, headers=headers)
    assert first.status_code == 201, first.text
    created = first.json()
    binding = created["constraints"]["storypack_binding"]
    assert binding["reviewed_packet_sha256"] == scoped_story["reviewed_packet_sha256"]
    assert binding["owner_subject_key"] == "pet:maotai"
    assert len(binding["owner_evidence"]) == 3
    assert binding["subject_sha256"] == scoped_story["confirmed_subject_sha256"]
    assert set(binding["assets"]) == {"character", "scene", "style"}
    workflow = services.workflows.get_workflow(created["workflow_id"])
    step = next(item for item in workflow.steps if item.step_key == "research-evidence")
    assert step.payload["owner_review_packet_sha256"] == scoped_story["reviewed_packet_sha256"]

    replay = studio.post(SCOPED_ROUTE, json=scoped_story, headers=headers)
    assert replay.status_code == 201, replay.text
    assert replay.json()["goal_id"] == created["goal_id"]
    assert replay.json()["workflow_id"] == created["workflow_id"]

    # Exercise the actual discovery handler with a deterministic local-analysis
    # fixture. A search call is forbidden; no worker/GPU/model server is started.
    from types import SimpleNamespace

    class NoExternalSearch:
        def search(self, **kwargs):
            raise AssertionError("Private scoped story attempted external research")

    class FixtureLocal:
        def analyze(self, request):
            return LocalAnalysisResult(
                role=request.role, summary="reviewed local claims",
                confidence=0.5, findings=["owner claims only"],
                evidence_ids=request.evidence_ids,
            )

    coordinator = ContentDiscoveryCoordinator(
        search=NoExternalSearch(), local=FixtureLocal(),
        owner_evidence=CanonicalEvidenceLedger(db),
    )
    result = coordinator.handler(SimpleNamespace(
        task_type="autonomous.discovery.v1", payload=step.payload,
        timeout_seconds=900, task_id="fixture",
    )).result_document
    assert result["search_count"] == 0
    assert result["search_evidence"] == []
    assert len(result["connected_evidence"]) == 3
    assert {row["reviewed_packet_sha256"] for row in result["connected_evidence"]} == {
        scoped_story["reviewed_packet_sha256"]
    }
    assert {row["evidence_id"] for row in result["connected_evidence"]} == {
        row["evidence_id"] for row in binding["owner_evidence"]
    }
    assert _counts(studio)[1:] == before[1:]
    assert db.scalar("SELECT COUNT(*) FROM production_attempts") == 0


@pytest.mark.parametrize("case,expected", [
    ("auth", 401), ("confirmation", 409), ("digest", 409),
    ("project", 409), ("role", 409), ("tamper", 409),
    ("packet", 409), ("wrong_photo", 409), ("subject", 409),
    ("duplicate_json", 422),
])
def test_scoped_goal_denials_never_create_goal(studio, scoped_story, case, expected):
    payload = copy.deepcopy(scoped_story)
    headers = {"X-Picotoo-Goal-Confirmed": "yes"}
    db = studio.app.state.services.database
    before = _counts(studio)
    before_goals = db.scalar("SELECT COUNT(*) FROM autonomous_goals")
    if case == "auth":
        headers["Authorization"] = "Bearer invalid"
    elif case == "confirmation":
        headers["X-Picotoo-Goal-Confirmed"] = "no"
    elif case == "digest":
        payload["confirmed_subject_sha256"] = "0" * 64
    elif case == "project":
        payload["project_id"] = _asset_project(studio)
    elif case == "role":
        payload["storypack"]["scene_ref"] = payload["storypack"]["character_ref"]
    elif case == "tamper":
        digest = hashlib.sha256(_ASSET_PNG).hexdigest()
        store = studio.app.state.services.results
        (store.objects_dir / digest[:2] / digest[2:]).write_bytes(b"tampered")
    elif case == "packet":
        payload["reviewed_packet_sha256"] = "0" * 64
    elif case == "wrong_photo":
        payload["reviewed_packet_sha256"] = _reviewed_packet(
            studio, "pet:maotai", "1" * 64, "A different image was explicitly reviewed."
        )
    elif case == "subject":
        payload["owner_subject_key"] = "pet:other"

    if case == "duplicate_json":
        body = json.dumps(payload).replace(
            '"project_id":', '"project_id":"duplicate","project_id":', 1
        )
        response = studio.post(SCOPED_ROUTE, content=body, headers={
            **headers, "Content-Type": "application/json",
        })
    else:
        response = studio.post(SCOPED_ROUTE, json=payload, headers=headers)
    assert response.status_code == expected, response.text
    assert db.scalar("SELECT COUNT(*) FROM autonomous_goals") == before_goals
    assert _counts(studio) == before
