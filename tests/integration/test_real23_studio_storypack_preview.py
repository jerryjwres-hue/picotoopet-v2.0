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


@pytest.mark.parametrize("dynamic", [False, True])
def test_scoped_goal_pins_exact_existing_packet_and_local_workflow(studio, scoped_story, dynamic):
    from picotoopet_core.autonomous.discovery import ContentDiscoveryCoordinator
    from picotoopet_core.autonomous.evidence_ledger import CanonicalEvidenceLedger
    from picotoopet_core.autonomous.local_intelligence import LocalAnalysisResult

    if dynamic:
        scoped_story["storypack"]["dynamic_motion"] = dynamic_dinner_pack()["dynamic_motion"]
        preview = studio.post(ROUTE, json=scoped_story["storypack"])
        assert preview.status_code == 200, preview.text
        scoped_story["confirmed_subject_sha256"] = preview.json()["owner_review_subject"]["subject_sha256"]

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

    # Exercise the genuine Creative coordinator and repositories with bounded
    # previously computed CPU fixture results. Only result lookup is substituted;
    # the actual Goal, ResultStore, source set and Creative job are durable facts.
    from picotoopet_core.autonomous.human_pipeline import GoalPipelineError
    from picotoopet_core.autonomous.local_creative import GoalLocalCreativeCoordinator
    from picotoopet_core.creative.execution import CreativeIntelligenceCoordinator

    synthesis = {
        "goal_id": created["goal_id"],
        "evidence_ids": result["evidence_ids"],
        "findings": ["Fixture interpretation of reviewed statements, not a verified fact."],
    }
    records = {}
    for task_id, document, result_type in (
        ("fixture-discovery", result, "autonomous.discovery.v1"),
        ("fixture-synthesis", synthesis, "autonomous.goal_synthesis.v1"),
    ):
        stored = services.results.put_json(
            document, result_type=result_type, max_bytes=256 * 1024
        )
        records[task_id] = SimpleNamespace(
            object_hash=stored.object_hash, result_type=result_type
        )
    prior_steps = SimpleNamespace(steps=[
        SimpleNamespace(step_key="research-evidence", task_id="fixture-discovery"),
        SimpleNamespace(step_key="evidence-synthesis", task_id="fixture-synthesis"),
    ])
    bridge = GoalLocalCreativeCoordinator(
        goals=services.autonomous_goals,
        workflows=SimpleNamespace(get_workflow=lambda _: prior_steps),
        result_records=SimpleNamespace(get_for_task=records.__getitem__),
        result_store=services.results,
        creative=services.creative,
    )
    bridge_task = SimpleNamespace(
        task_type="autonomous.goal_creative.v1",
        payload={"goal_id": created["goal_id"]},
    )
    job_result = bridge.handler(bridge_task).result_document
    job_id = job_result["creative_job_id"]
    job = services.creative.get_job(job_id)
    source = services.creative_source.load_persisted_source_set(job_id)
    assert job.creative_profile.value == "creative.content_plan.v2"
    assert set(source.evidence_ids) == set(result["evidence_ids"])
    owner_findings = [
        item.finding for item in source.findings
        if item.finding.get("source_type") == "owner_subject_attestation"
    ]
    assert len(owner_findings) == 3
    assert {item["reviewed_packet_sha256"] for item in owner_findings} == {
        binding["reviewed_packet_sha256"]
    }
    assert bridge.handler(bridge_task).result_document["creative_job_id"] == job_id
    assert db.scalar(
        "SELECT COUNT(*) FROM tasks WHERE resource_tag=?", (f"creative:{job_id}",)
    ) == 0
    assert services.creative.get_package(job_id) is None

    if dynamic:
        _verify_dynamic_creative_and_production_gate(studio, created, binding, job, source)
        return

    # A post-Goal modification cannot pass either handoff or pre-model Creative.
    digest = binding["assets"]["character"]["sha256"]
    target = services.results.objects_dir / digest[:2] / digest[2:]
    target.write_bytes(b"tampered after registration")
    with pytest.raises(GoalPipelineError, match="STORY_GOAL_PINNED_ASSET_CHANGED"):
        bridge.handler(bridge_task)

    class NoModel:
        def run(self, *args, **kwargs):
            raise AssertionError("Invalid assets must stop before model inference")

    execution = CreativeIntelligenceCoordinator(
        database=db, queue=None, repository=services.creative_repository,
        source_normalizer=services.creative_source, store=services.creative_store,
        adapter=NoModel(), configured_model_id="cpu-fixture-not-a-live-model",
    )
    execution.handler(SimpleNamespace(payload={
        "creative_job_id": job_id,
        "source_set_digest": job.source_set_digest,
        "creative_profile": job.creative_profile.value,
    }))
    rejected = services.creative.get_job(job_id)
    assert rejected.failure_code == "STORY_GOAL_PINNED_ASSET_CHANGED"
    assert services.creative.get_package(job_id) is None
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


def dynamic_dinner_pack():
    pack = storypack()
    # 字段均为测试剧本中的显式空间描述，不是用户真实资产或物理测量。
    pack["dynamic_motion"] = {
        "policy": "dynamic-pet-feeding-v1.0.0",
        "start_location": "the doorway",
        "bowl_location": "the dining corner",
        "support_surface": "wood floor",
        "bowl_description": "round steel bowl",
        "screen_direction": "LEFT_TO_RIGHT",
        "shots": [
            {"shot_id": "S01", "event": "NOTICE_BOWL", "framing": "wide full-body shot"},
            {"shot_id": "S02", "event": "APPROACH_BOWL", "framing": "medium full-body shot"},
            {"shot_id": "S03", "event": "BEGIN_EATING", "framing": "close shot of muzzle and bowl"},
        ],
    }
    return pack


def test_dynamic_storypack_projects_motion_without_granting_authority(studio):
    pack = dynamic_dinner_pack()
    before = _counts(studio)
    first = studio.post(ROUTE, json=pack)
    assert first.status_code == 200, first.text
    preview = first.json()
    motion = preview["dynamic_motion_proposal"]
    assert motion["storypack_sha256"] == preview["storypack_sha256"]
    assert motion["status"] == "DYNAMIC_PROPOSAL_REQUIRES_OWNER_REVIEW"
    assert motion["planned_payoff"] == "START_NOT_EATING_TO_AT_BOWL_EATING"
    assert [item["event"] for item in motion["shots"]] == [
        "NOTICE_BOWL", "APPROACH_BOWL", "BEGIN_EATING"
    ]
    states = motion["states"]
    assert [item["location"] for item in states] == ["START", "START", "AT_BOWL", "AT_BOWL"]
    assert [item["feeding"] for item in states] == ["NOT_EATING"] * 3 + ["EATING"]
    assert states[-1]["posture"] == "STANDING_HEAD_LOWERED"
    assert "walks left to right" in motion["shots"][1]["visible_action"]
    assert "first bites" in motion["shots"][2]["visible_action"]
    assert [item["source_action"] for item in motion["shots"]] == [
        item["action"] for item in pack["shots"]
    ]
    assert all(
        a["closing_state"] == b["opening_state"]
        for a, b in zip(motion["shots"], motion["shots"][1:])
    )
    assert all(motion[key] is False for key in ("owner_approved", "can_queue", "gpu_post_authorized"))
    assert preview["canonical_goal_intake"]["ready_for_user_submission"] is False
    assert preview["canonical_goal_intake"]["objective"] is None
    assert "DYNAMIC_SCOPED_GOAL_REQUIRED" in (
        preview["canonical_goal_intake"]["blocking_reasons"]
    )
    assert preview["can_queue"] is False
    assert studio.post(ROUTE, json=pack).json() == preview

    changed = copy.deepcopy(pack)
    changed["dynamic_motion"]["screen_direction"] = "RIGHT_TO_LEFT"
    second = studio.post(ROUTE, json=changed)
    assert second.status_code == 200, second.text
    new = second.json()
    assert new["storypack_sha256"] != preview["storypack_sha256"]
    assert new["dynamic_motion_proposal"]["motion_digest"] != motion["motion_digest"]
    assert "walks right to left" in new["dynamic_motion_proposal"]["shots"][1]["visible_action"]
    assert all(
        a["input_sha256"] != b["input_sha256"]
        for a, b in zip(preview["fingerprint_plan"]["shots"], new["fingerprint_plan"]["shots"])
    )
    assert _counts(studio) == before


def test_motion_extension_does_not_change_legacy_digest(studio):
    from picotoopet_core.domain.storypack import StoryPackV1

    pack = storypack()
    old = StoryPackV1.model_validate(pack).model_dump(mode="json", exclude={"dynamic_motion"})
    expected = hashlib.sha256(json.dumps(
        old, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    normal = studio.post(ROUTE, json=pack).json()
    explicit_null = studio.post(ROUTE, json={**pack, "dynamic_motion": None}).json()
    assert normal["storypack_sha256"] == expected
    assert normal == explicit_null
    assert "dynamic_motion_proposal" not in normal
    assert normal["canonical_goal_intake"]["ready_for_user_submission"] is True


@pytest.mark.parametrize("case", [
    "event_order", "same_location", "close_approach", "duplicate_framing",
    "foreign_shot", "noncontinuous", "portrait", "extra_cast", "fake_approval",
])
def test_dynamic_motion_invalid_input_fails_closed(studio, case):
    pack = dynamic_dinner_pack()
    motion = pack["dynamic_motion"]
    if case == "event_order":
        motion["shots"][0]["event"] = "BEGIN_EATING"
    elif case == "same_location":
        motion["bowl_location"] = motion["start_location"]
    elif case == "close_approach":
        motion["shots"][1]["framing"], motion["shots"][2]["framing"] = (
            motion["shots"][2]["framing"], motion["shots"][1]["framing"]
        )
    elif case == "duplicate_framing":
        motion["shots"][1]["framing"] = motion["shots"][0]["framing"]
    elif case == "foreign_shot":
        motion["shots"][2]["shot_id"] = "S99"
    elif case == "noncontinuous":
        pack["shots"][1]["handoff"] = "cut"
    elif case == "portrait":
        pack["output_profile"] = "design_portrait"
    elif case == "extra_cast":
        pack["supporting_character_refs"] = ["other_pet"]
    else:
        motion["owner_approved"] = True
    before = _counts(studio)
    assert studio.post(ROUTE, json=pack).status_code == 422
    assert _counts(studio) == before


def test_dynamic_motion_uses_existing_bible_and_shot_plan_but_stays_unapproved():
    from picotoopet_core.creative.dynamic_pet_story import bind_dynamic_bible_proposal
    from picotoopet_core.creative.models import (
        CreativeQualityOutcome, CreativeScriptResult, CreativeStageKind, ShotPlanResult,
    )
    from picotoopet_core.creative.profiles import creative_profile_definition
    from picotoopet_core.creative.quality import CreativeQualityGate
    from picotoopet_core.creative.source import NormalizedCreativeSourceSet
    from picotoopet_core.creative.video_bible import (
        SceneSpec, SubjectIdentity, derive_shot_plan, evaluate_story_storyboard, seal_bible,
        shot_plan_integrity_findings,
    )
    from picotoopet_core.domain.storypack import StoryPackV1

    pack = StoryPackV1.model_validate(dynamic_dinner_pack())
    script = CreativeScriptResult.model_validate({
        "schema_version": "1.0", "creative_profile": "creative.content_plan.v1",
        "script_id": "fixture", "title": "Dinner", "target_duration_seconds": 12,
        "cta_beat_id": "beat-3",
        "beats": [
            {"beat_id": f"beat-{index}", "order": index, "duration_seconds": 4,
             "visual_intent": shot.action}
            for index, shot in enumerate(pack.shots, 1)
        ],
    })
    subject = SubjectIdentity(
        subject_id="fixture-pet", kind="PET", species="dog", breed_or_type="Alaskan Malamute",
        coat_or_appearance="gray and white fur", distinguishing_marks=["green scarf"],
        identity_phrase="Alaskan Malamute dog with gray and white fur and green scarf",
    )
    scene = SceneSpec(
        scene_id="dining", environment_phrase="a dining corner with a round steel bowl on the wood floor",
        lighting_phrase="soft warm window light", palette=["warm", "wood"],
    )
    draft = bind_dynamic_bible_proposal(pack, script, subject, scene)
    assert draft.needs_human is True
    assert draft.product is None
    assert draft.subject == subject
    assert draft.scenes == [scene]
    assert not evaluate_story_storyboard(draft, product_required=False)
    assert draft.shots[0].opening_state != draft.shots[-1].closing_state

    # 仅测试原投影函数能保留动作/角色/道具；不持久化，不创建包或生产任务。
    sealed = seal_bible(
        draft, project_key="fixture", source_set_digest="a" * 64, selected_idea_id="idea-1"
    )
    projected = derive_shot_plan(sealed, script)
    plan = ShotPlanResult.model_validate(projected)
    assert all(item.subject == subject.identity_phrase for item in plan.shots)
    assert all("round steel bowl" in " ".join(item.continuity_keys) for item in plan.shots)
    assert "walks left to right" in plan.shots[1].action
    assert "first bites" in plan.shots[2].action
    assert not shot_plan_integrity_findings(sealed, script, projected)

    # 真实 Creative quality gate 必须拒绝未经动态 Owner 审核的 Bible。
    source = NormalizedCreativeSourceSet(
        project_key="fixture", result_package_ids=[], result_digests=[],
        findings=[], evidence_ids=[], source_set_digest="a" * 64,
    )
    decision, _ = CreativeQualityGate().evaluate(
        stage_kind=CreativeStageKind.VIDEO_BIBLE,
        profile=creative_profile_definition("creative.content_plan.v2"),
        source_set=source, previous_stages={}, raw_result=draft.model_dump(mode="json"),
        objective="纯宠物视频，明确要求3个镜头，每个镜头4秒",
    )
    assert decision.outcome is CreativeQualityOutcome.NEEDS_HUMAN


def _verify_dynamic_creative_and_production_gate(studio, created, binding, job, source):
    """Real SQLite owner review and canonical durable Creative stages, CPU model fixture only."""
    from types import SimpleNamespace

    from picotoopet_core.autonomous.owner_structured_review import (
        OwnerStructuredReviewCommitRequest, OwnerStructuredReviewError,
        OwnerStructuredReviewPreviewRequest, OwnerStructuredReviewService,
    )
    from picotoopet_core.creative.execution import (
        CreativeIntelligenceCoordinator, load_trusted_pet_creative_binding,
        verify_current_pet_binding,
    )
    from picotoopet_core.production.models import ProductionJobCreateRequest
    from picotoopet_core.security.owner_principal import OwnerPrincipal

    services = studio.app.state.services
    db = services.database
    principal = OwnerPrincipal(
        actor_id="fixture-owner", credential_id="fixture-credential",
        subject_keys=("pet:maotai",), permissions=("owner_facts.review",),
        registry_revision=1,
    )
    review = OwnerStructuredReviewService(db)
    proposal = review.proposal(created["goal_id"], principal)
    motion = proposal.dynamic_motion_proposal
    assert motion["motion_digest"] == binding["dynamic_motion_digest"]
    values = {
        "subject_lock.subject_id": "maotai",
        "subject_lock.species": "dog",
        "subject_lock.breed_or_type": "Alaskan Malamute",
        "subject_lock.coat_or_appearance": "gray and white fur",
        "subject_lock.distinguishing_marks": ["green scarf"],
        "pose_lock.body_pose": "standing",
        "pose_lock.head_direction": "looking away from the bowl",
        "pose_lock.support_surface": "wood floor",
        "scene_lock.environment": "dining room doorway and corner",
        "scene_lock.lighting": "warm window light",
        "scene_lock.temporary_accessories": ["green scarf"],
        "camera_lock.allowed_framings": [item["framing"] for item in motion["shots"]],
        "allowed_events": [item["event"] for item in motion["shots"]],
    }
    body = {
        "goal_id": created["goal_id"],
        "review_actor_id": principal.actor_id,
        "proposal_digest": proposal.proposal_digest,
        "decisions": [
            {"field_path": key, "decision": "CORRECT", "corrected_value": value}
            for key, value in values.items()
        ],
        "story_policy_opt_in": "dynamic-pet-feeding-v1.0.0",
        "confirmed_motion_digest": motion["motion_digest"],
    }
    before = db.scalar("SELECT COUNT(*) FROM canonical_evidence")
    for patch in (
        {"story_policy_opt_in": "static-pet-story-v1.0.0"},
        {"confirmed_motion_digest": "0" * 64},
        {"confirmed_motion_digest": None},
    ):
        with pytest.raises(OwnerStructuredReviewError, match="MOTION_CONFIRMATION_REQUIRED"):
            review.preview(OwnerStructuredReviewPreviewRequest.model_validate({**body, **patch}), principal)
    assert db.scalar("SELECT COUNT(*) FROM canonical_evidence") == before
    assert db.scalar("SELECT COUNT(*) FROM tasks WHERE resource_tag=?", (f"creative:{job.creative_job_id}",)) == 0
    request = OwnerStructuredReviewPreviewRequest.model_validate(body)
    reviewed = review.preview(request, principal)
    assert reviewed.outcome == "READY", reviewed.reason_codes
    assert reviewed.state_facts.facts_version == 2
    assert reviewed.state_facts.pose_lock.fixed is False
    commit_request = OwnerStructuredReviewCommitRequest(
        preview_request=request, source_revision_digest=reviewed.source_revision_digest,
        review_digest=reviewed.review_digest, preview_digest=reviewed.preview_digest,
    )
    commit = review.commit(commit_request, principal, idempotency_key="fixture-dynamic-review")
    assert review.commit(commit_request, principal, idempotency_key="fixture-dynamic-review") == commit
    assert db.scalar("SELECT COUNT(*) FROM tasks WHERE resource_tag=?", (f"creative:{job.creative_job_id}",)) == 1
    trusted = load_trusted_pet_creative_binding(db, job)
    assert trusted.dynamic_pack is not None
    assert verify_current_pet_binding(db, job, trusted)

    class TwoCallFixture:
        def __init__(self):
            self.calls = []

        def run(self, stage, context, *, correction=None):
            kind = stage.stage_kind.value
            self.calls.append(kind)
            refs = [source.findings[0].source_finding_ref]
            evidence = source.evidence_ids
            header = {"schema_version": "1.0", "creative_profile": "creative.content_plan.v1"}
            assert context["trusted_dynamic_story"]["motion"]["motion_digest"] == motion["motion_digest"]
            if kind == "idea_ranking.v1":
                return {**header, "ideas": [
                    {
                        "idea_id": f"idea-{i}", "rank": i, "title": "Dinner",
                        "audience_problem": "short pet story", "hook": "pet notices dinner",
                        "angle": "a small daily moment", "value_proposition": "warmth",
                        "format_hint": "short film", "confidence": 0.8,
                        "source_finding_refs": refs, "source_evidence_ids": evidence,
                        "claim_risk": "LOW",
                    } for i in range(1, 4)
                ]}
            if kind == "creative_brief.v1":
                return {
                    **header, "selected_idea_id": "idea-1",
                    "target_audience": "pet lovers", "customer_problem": "short story",
                    "value_proposition": "warmth", "primary_hook": "pet notices dinner",
                    "emotional_tone": "warm", "content_format": "short film",
                    "output_profile_id": "video.landscape.v1",
                    "duration_min_seconds": 12, "duration_max_seconds": 12,
                    "message_hierarchy": ["discover", "approach", "eat"],
                    "required_source_finding_refs": refs,
                    "required_source_evidence_ids": evidence,
                    "cta_intent": "quiet ending",
                }
            raise AssertionError(f"Owner-reviewed action was unnecessarily rewritten: {kind}")

    model = TwoCallFixture()
    coordinator = CreativeIntelligenceCoordinator(
        database=db, queue=None, repository=services.creative_repository,
        source_normalizer=services.creative_source, store=services.creative_store,
        adapter=model, configured_model_id="cpu-fixture-not-a-live-model",
    )
    task = SimpleNamespace(payload={
        "creative_job_id": job.creative_job_id, "source_set_digest": job.source_set_digest,
        "creative_profile": job.creative_profile.value,
    })
    outcome = coordinator.handler(task)
    assert outcome.summary["status"] == "creative_ready", (
        outcome.summary, services.creative.get_job(job.creative_job_id)
    )
    assert model.calls == ["idea_ranking.v1", "creative_brief.v1"]
    package = services.creative.get_package(job.creative_job_id)
    stages = package.manifest["stage_results"]
    assert package.quality_outcome.value == "PASS"
    assert stages["dynamic_story_review.v1"]["motion_digest"] == motion["motion_digest"]
    assert stages["dynamic_story_review.v1"]["render_authorized"] is False
    assert len(stages["keyframe_kit.v1"]["keyframes"]) == 3
    assert all("round steel bowl" in item["still_prompt"] for item in stages["keyframe_kit.v1"]["keyframes"])
    assert "walks left to right" in stages["shot_plan.v1"]["shots"][1]["action"]
    assert "first bites" in stages["shot_plan.v1"]["shots"][2]["action"]
    coordinator.handler(task)
    assert model.calls == ["idea_ranking.v1", "creative_brief.v1"]
    assert services.creative.get_package(job.creative_job_id).creative_package_id == package.creative_package_id
    assert services.production.requires_reviewed_references(package)
    assert services.production._verify_dynamic_reference_scope(package)
    with pytest.raises(ValueError, match="REVIEWED_REFERENCES_REQUIRED"):
        services.production.create_job(ProductionJobCreateRequest(
            creative_package_id=package.creative_package_id,
            idempotency_key="fixture-no-t2v-downgrade",
        ))
    # No dynamic package or text gate is evidence of visual quality or render authority.
    assert db.scalar("SELECT COUNT(*) FROM production_jobs") == 0
    assert db.scalar("SELECT COUNT(*) FROM production_attempts") == 0
    assert db.scalar("SELECT COUNT(*) FROM approvals") == 0

    # 01. Exercise the positive dynamic route, not just the legacy static v2 fixture.
    #     References below are synthetic Windows claims; Mac has not read image bytes.
    shots = [item["shot_id"] for item in stages["shot_plan.v1"]["shots"]]
    claims = []
    for i, shot_id in enumerate(shots, 1):
        sha = f"{i:064x}"
        claims.append({
            "shot_id": shot_id, "input_relative_path": f"PicotooPet/references/{sha}/{shot_id}.png",
            "sha256": sha, "bytes": 4096 + i, "source_reference": "USER_SUPPLIED",
            "source_digest": sha, "rights_scope": "wan22.i2v.production.v1",
        })
    batch_route = "/api/v1/production/references/batches"
    batch_request = {
        "schema_version": "reference_batch.v1", "goal_id": created["goal_id"],
        "creative_package_id": package.creative_package_id,
        "creative_package_digest": package.package_digest,
        "selected_references": claims, "user_confirms_preview_and_rights": True,
    }
    registered = studio.post(batch_route, json=batch_request,
                             headers={"Idempotency-Key": "dynamic-fixture-three-refs"})
    assert registered.status_code == 201, registered.text
    receipt = registered.json()
    assert receipt["status"] == "Pending"
    assert studio.post(batch_route, json=batch_request,
                       headers={"Idempotency-Key": "dynamic-fixture-three-refs"}).json() == receipt
    assert db.scalar("SELECT COUNT(*) FROM production_jobs") == 0

    # 02. Pending cannot create a plan; only a synthetic explicit decision may approve.
    from picotoopet_core.production.versioned_plan import ProductionJobCreateV11Request

    create = {
        "schema_version": "1.1", "creative_package_id": package.creative_package_id,
        "idempotency_key": "dynamic-fixture-three-shot-plan",
        "approved_reference_ids": [receipt["approval_id"]], "pilot_first_shot": False,
    }
    with pytest.raises(ValueError, match="PRODUCTION_V11_REFERENCE_NOT_APPROVED"):
        services.production.create_job_v11(ProductionJobCreateV11Request.model_validate(create))
    services.approvals.decide_for_control_center(
        approval_id=receipt["approval_id"], decision="approve",
        request_digest=receipt["approval_request_digest"],
        idempotency_key="dynamic-fixture-approve-refs",
        resolved_by="synthetic-fixture", reason="offline CPU test only",
    )
    assert studio.get(batch_route + "/" + receipt["approval_id"]).json()["status"] == "Approved"

    # 03. Actual authenticated full-plan HTTP route binds all three dynamic shots.
    route = "/api/v1/production/jobs/v1.1"
    response = studio.post(route, json=create)
    assert response.status_code in (200, 201), response.text
    production_job = response.json()
    production_id = production_job["production_job_id"]
    assert production_job["lease_executor_id"] is None
    assert studio.post(route, json=create).json()["production_job_id"] == production_id
    plan_response = studio.get(f"/api/v1/production/jobs/{production_id}/plan")
    assert plan_response.status_code == 200, plan_response.text
    plan = plan_response.json()
    assert plan["schema_version"] == "1.1"
    assert plan["target_runtime_ms"] == 12000
    assert [item["shot_id"] for item in plan["tasks"]] == shots
    assert "walks left to right" in plan["tasks"][1]["positive_prompt"]
    assert "first bites" in plan["tasks"][2]["positive_prompt"]
    for task_plan, claim in zip(plan["tasks"], claims, strict=True):
        assert task_plan["render_intent"] == "IMAGE_TO_VIDEO"
        assert task_plan["workflow_id"] == "comfy.wan22.ti2v5b.i2v.v1"
        assert (task_plan["width"], task_plan["height"], task_plan["fps"],
                task_plan["frame_count"], task_plan["target_duration_ms"]) == (832, 480, 24, 97, 4000)
        ref = task_plan["reference_asset"]
        assert ref["approval_id"] == receipt["approval_id"]
        assert ref["approval_request_digest"] == receipt["approval_request_digest"]
        assert ref["sha256"] == claim["sha256"]
        assert ref["input_relative_path"] == claim["input_relative_path"]
        assert ref["goal_id"] == created["goal_id"]
    assert services.production._digest(plan) == production_job["plan_digest"]
    assert db.scalar("SELECT COUNT(*) FROM production_jobs") == 1
    assert db.scalar("SELECT COUNT(*) FROM production_attempts") == 0
    assert db.scalar("SELECT COUNT(*) FROM production_jobs WHERE lease_executor_id IS NOT NULL") == 0
    assert services.creative.get_package(job.creative_job_id).package_digest == package.package_digest

    # 04. Altered source bytes stop the existing frozen plan authorization as well.
    digest = binding["assets"]["character"]["sha256"]
    target = services.results.objects_dir / digest[:2] / digest[2:]
    target.write_bytes(b"tampered after Creative PASS")
    with pytest.raises(ValueError, match="STORY_GOAL_PINNED_ASSET_CHANGED"):
        services.production._verify_dynamic_reference_scope(package)
    with pytest.raises(ValueError, match="STORY_GOAL_PINNED_ASSET_CHANGED"):
        services.production.authorize_reference_v11(production_id, plan["tasks"][0]["production_task_id"])
    assert db.scalar("SELECT COUNT(*) FROM production_attempts") == 0


def test_first_owner_packet_lookup_is_readonly_before_any_commit(studio):
    """Fresh Core has its canonical ledger ready before the first Film Studio lookup."""
    db = studio.app.state.services.database
    # 01. Before any owner evidence endpoint is called, startup has initialized the ledger.
    assert db.scalar("SELECT MAX(version) FROM schema_migrations") == 24
    assert db.scalar("SELECT COUNT(*) FROM canonical_evidence") == 0
    project_id = _asset_project(studio)
    uploaded = studio.post(
        ASSET_ROUTE, content=_ASSET_PNG,
        headers=_asset_headers(project_id, "character", _ASSET_PNG),
    )
    assert uploaded.status_code == 201, uploaded.text
    query = {
        "project_id": project_id,
        "character_ref": uploaded.json()["artifact_id"],
        "subject_key": "pet:first-lookup",
    }

    # 02. Empty and repeated queries must be genuine reads, not lazy schema creation.
    route = "/api/v1/studio/owner-subject-packets"
    before = _counts(studio)
    changes_before = db.connection.total_changes
    schema_before = db.scalar("PRAGMA schema_version")
    for _ in range(2):
        result = studio.get(route, params=query)
        assert result.status_code == 200, result.text
        assert result.json()["packets"] == []
        assert all(result.json()[flag] is False for flag in (
            "owner_approved", "production_approval_granted", "can_queue",
        ))
    assert db.connection.total_changes == changes_before
    assert db.scalar("PRAGMA schema_version") == schema_before
    assert db.scalar("SELECT COUNT(*) FROM canonical_evidence") == 0
    assert _counts(studio) == before


def test_reviewed_packets_are_scoped_reusable_and_recomputed(studio, scoped_story):
    db = studio.app.state.services.database
    pack = scoped_story["storypack"]
    query = {
        "project_id": scoped_story["project_id"],
        "character_ref": pack["character_ref"],
        "subject_key": scoped_story["owner_subject_key"],
    }
    route = "/api/v1/studio/owner-subject-packets"
    # Later unrelated photo claims must never auto-select for the current character bytes.
    _reviewed_packet(studio, "pet:maotai", "1" * 64, "The pet plans to visit the doorway.")
    before = _counts(studio)
    result = studio.get(route, params=query)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["project_id"] == query["project_id"]
    assert body["character_ref"] == query["character_ref"]
    assert body["character_sha256"] == hashlib.sha256(_ASSET_PNG).hexdigest()
    assert [packet["packet_digest"] for packet in body["packets"]] == [
        scoped_story["reviewed_packet_sha256"]
    ]
    assert {claim["kind"] for claim in body["packets"][0]["claims"]} == {
        "visible_identity", "visible_scene", "creative_intent"
    }
    assert all(body[key] is False for key in ("owner_approved", "production_approval_granted", "can_queue"))
    assert studio.get(route, params=query, headers={"Authorization": "Bearer invalid"}).status_code == 401
    assert studio.get(route, params={**query, "project_id": "unrelated"}).status_code == 409
    assert studio.get(route, params={**query, "character_ref": pack["scene_ref"]}).status_code == 409
    assert studio.get(route, params={**query, "subject_key": "pet:other"}).json()["packets"] == []
    assert _counts(studio) == before

    # Recompute the original packet digest from its ordered claims. Even if the
    # altered text and raw row hash agree, it is not the owner's reviewed packet.
    original = db.fetchone(
        "SELECT evidence_id FROM canonical_evidence WHERE origin_ref=?",
        (f"pet-owner:{scoped_story['reviewed_packet_sha256']}:claim:01",),
    )
    text = "Unexpected replacement of the reviewed identity statement."
    with db.transaction() as conn:
        conn.execute("UPDATE canonical_evidence SET text_value=?,raw_hash=? WHERE evidence_id=?",
                     (text, hashlib.sha256(text.encode()).hexdigest(), original["evidence_id"]))
    assert studio.get(route, params=query).json()["packets"] == []
    denied = studio.post(SCOPED_ROUTE, json=scoped_story, headers={"X-Picotoo-Goal-Confirmed": "yes"})
    assert denied.status_code == 409
    assert db.scalar("SELECT COUNT(*) FROM autonomous_goals") == 0
    assert _counts(studio) == before
