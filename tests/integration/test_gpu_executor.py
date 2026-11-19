import base64
import hashlib
import io
import json
import secrets
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
import yaml
from fastapi.testclient import TestClient
from PIL import Image
from requests import ConnectionError, Session

from picotoopet_core.api.app import create_app
from picotoopet_core.api.routes import history_imports
from picotoopet_core.audit.verifier import verify_audit_chain
from picotoopet_core.cli import main
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths
from scripts.windows.executor_bridge import Bridge, BridgeConfig


@pytest.fixture
def api(tmp_path):
    token = secrets.token_hex(24)
    app = create_app(AppSettings(paths=RuntimePaths.from_root(tmp_path), api_token=token))
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        yield client


LEASE = {"worker_id": "bridge", "resource_tags": ["gpu-5070ti"], "lease_seconds": 60}


def media(kind="image", digest="0", take=1):
    return {
        "kind": kind,
        "path": f"fixture-{digest}",
        "sha256": digest * 64,
        "bytes": 1,
        "shot_id": "S01",
        "take": take,
    }


def finish_gate(api, passed=True, jpeg=None):
    gate = api.post("/api/v1/executors/lease", json=LEASE).json()
    assert gate["task_type"] == "qc.check"
    jobs = gate["payload"]["jobs"]
    report = {
        "passed": passed,
        "score": 95 if passed else 30,
        "fails": [] if passed else ["重复帧"],
    }
    by_hash = {item["sha256"]: report for item in jobs["artifacts"]}
    body = {
        "worker_id": "bridge",
        "artifacts": [],
        "metrics": {"seconds": 1},
        "qc": {**report, "by_sha256": by_hash},
    }
    url = f"/api/v1/tasks/{gate['task_id']}"
    if jpeg:
        assert (
            api.post(
                url + "/thumbnails", data={"worker_id": "bridge"}, files={"file": jpeg}
            ).status_code
            == 201
        )
    response = api.post(url + "/complete", json=body)
    assert response.status_code == 200, response.text
    assert api.post(url + "/complete", json=body).json() == response.json()
    return response.json()


def test_executor_complete_and_review(api):
    task = api.post(
        "/api/v1/tasks",
        json={
            "task_type": "gen.keyframe",
            "resource_tag": "gpu-5070ti",
            "payload": {
                "episode_id": "demo",
                "shot_id": "S01",
                "runner": "run_qwen_edit.py",
                "jobs": {},
                "args": [],
            },
        },
    ).json()
    lease = {"worker_id": "bridge", "resource_tags": ["gpu-5070ti"], "lease_seconds": 60}
    endpoint = f"/api/v1/tasks/{task['task_id']}"
    assert (
        api.post("/api/v1/executors/lease", json={**lease, "resource_tags": ["other"]}).status_code
        == 204
    )
    assert api.post("/api/v1/executors/lease", json=lease).json()["status"] == "Running"
    assert (
        api.post(
            endpoint + "/heartbeat",
            json={
                "worker_id": "other",
                "progress": 0.5,
                "message": "working",
            },
        ).status_code
        == 409
    )
    assert (
        api.post(
            endpoint + "/heartbeat",
            json={
                "worker_id": "bridge",
                "progress": 0.5,
                "message": "working",
            },
        ).status_code
        == 200
    )
    complete = {
        "worker_id": "bridge",
        "artifacts": [
            {
                "kind": "image",
                "path": r"C:\demo\frame.png",
                "sha256": hashlib.sha256(b"demo").hexdigest(),
                "bytes": 4,
                "shot_id": "S01",
                "take": 1,
            }
        ],
        "qc": {"passed": True},
        "metrics": {"seconds": 3},
    }
    assert api.post(endpoint + "/complete", json=complete).json()["status"] == "Completed"
    assert api.post(endpoint + "/complete", json=complete).status_code == 200
    (artifact,) = api.get(endpoint + "/artifacts").json()["artifacts"]
    finish_gate(api)
    decision_url = f"/api/v1/artifacts/{artifact['artifact_id']}/decision"
    assert api.post(decision_url, json={"decision": "pick", "note": "演示"}).status_code == 200
    assert api.get(endpoint + "/artifacts").json()["artifacts"][0]["decision"] == "pick"
    services = api.app.state.services
    assert verify_audit_chain(services.database).valid
    assert (
        services.database.scalar(
            "SELECT COUNT(*) FROM audit_events WHERE action='executor.complete' AND resource_id=?",
            (task["task_id"],),
        )
        == 1
    )


def episode_spec():
    return {
        "episode_id": "demo",
        "title": "假数据",
        "target_seconds": 3,
        "characters": ["角色"],
        "shots": [
            {
                "shot_id": "S01",
                "seconds": 3,
                "beat": "等待",
                "emotion": "平静",
                "camera": {"move": "固定", "lens": 35, "speed": 1},
                "first_frame": {"refs": [], "prompt": "纯色"},
                "video": {"prompt": "纯色", "negative": "", "seeds": [1]},
                "audio": {"vocal_from": "none", "foley": ["脚步"]},
                "transition_out": {"type": "cut", "offset_s": 0},
            }
        ],
        "edit": {"fps": 24, "size": [576, 768], "loudness_lufs": -14},
    }


def imported_candidate(take=1, **updates):
    candidate = {
        "kind": "video",
        "path": rf"D:\Demo\take-{take}.mp4",
        "sha256": hashlib.sha256(f"take-{take}".encode()).hexdigest(),
        "bytes": 16,
        "shot_id": "S01",
        "take": take,
        "seed": 100 + take,
        "source_id": f"fake-receipt:S01:v{take}",
    }
    return candidate | updates


def test_historical_import_preserves_takes_and_does_not_run_worker(api):
    shot = imported_candidate(1, decision="pick", qc={"score": 92})
    buffer = io.BytesIO()
    Image.new("RGB", (16, 12), (10, 20, 30)).save(buffer, "JPEG")
    shot["jpeg_base64"] = base64.b64encode(buffer.getvalue()).decode()
    body = {"episode": episode_spec(), "candidates": [shot, imported_candidate(2)]}
    endpoint = "/api/v1/episodes/import"
    response = api.post(endpoint, json=body)
    assert response.status_code == 201
    assert response.json() == {"episode_id": "demo", "inserted_count": 2, "existing_count": 0}
    assert api.get("/api/v1/episodes").json()[0]["episode_id"] == "demo"
    review = api.get("/api/v1/episodes/demo/review").json()
    assert review["can_assemble"] is False  # 历史素材未取得可信 QC 认证，不得直接合成。
    first, second = review["shots"][0]["candidates"]
    assert (first["seed"], first["source_id"], first["qc"]) == (101, shot["source_id"], shot["qc"])
    assert (first["decision"], second["take"], second["seed"]) == ("pick", 2, 102)
    thumbnails = f"/api/v1/tasks/{first['task_id']}/thumbnails"
    thumbnail = api.get(f"{thumbnails}/{first['thumbnail_id']}").json()
    assert thumbnail["jpeg_base64"] == shot["jpeg_base64"]
    artifacts = api.get(f"/api/v1/tasks/{first['task_id']}/artifacts").json()
    assert artifacts["artifacts"][0]["source_id"] == shot["source_id"]
    result = api.get(f"/api/v1/results/{artifacts['result_id']}").json()
    assert result["result_type"] == "production_import"
    assert result["manifest"]["artifacts"][0]["seed"] == 101
    decision_url = f"/api/v1/artifacts/{second['artifact_id']}/decision"
    assert api.post(decision_url, json={"decision": "pick", "note": "approved"}).status_code == 200
    again = api.post(endpoint, json=body)
    assert again.status_code == 200
    assert again.json()["existing_count"] == 2
    assert (
        api.post(
            endpoint,
            json={
                "episode": body["episode"],
                "candidates": [
                    imported_candidate(
                        2, path=r"D:\Demo\other-batch.mp4", decision="pick", seed=103
                    ),
                ],
            },
        ).status_code
        == 201
    )
    review = api.get("/api/v1/episodes/demo/review").json()
    assert [item["decision"] for item in review["shots"][0]["candidates"]] == [None, "pick", None]
    lease = {"worker_id": "bridge", "resource_tags": ["gpu-5070ti"], "lease_seconds": 60}
    assert api.post("/api/v1/executors/lease", json=lease).status_code == 204
    services = api.app.state.services
    assert services.database.scalar("SELECT count(*) FROM task_events") == 0
    assert services.database.scalar("SELECT count(*) FROM executor_leases") == 0
    assert (
        services.database.scalar("SELECT count(*) FROM event_outbox WHERE topic='episode.imported'")
        == 2
    )
    assert verify_audit_chain(services.database).valid
    assert api.post("/api/v1/episodes/demo/assemble").status_code == 409


def test_historical_import_validates_batch_before_writing(api):
    url = "/api/v1/episodes/import"
    base = {"episode": episode_spec(), "candidates": [imported_candidate()]}
    assert api.post(url, json=base, headers={"Authorization": "Bearer denied"}).status_code == 401
    bad = [imported_candidate(), imported_candidate(2, shot_id="S99")]
    assert api.post(url, json=base | {"candidates": bad}).status_code == 422
    assert api.get("/api/v1/episodes").json() == []
    bad = [imported_candidate(path=r"D:\Demo\take.exe")]
    assert api.post(url, json=base | {"candidates": bad}).status_code == 422
    bad = [imported_candidate(jpeg_base64="eA==")]
    assert api.post(url, json=base | {"candidates": bad}).status_code == 415
    assert api.get("/api/v1/episodes").json() == []
    assert api.post(url, json=base).status_code == 201
    mismatched = base | {"episode": base["episode"] | {"title": "different"}}
    assert api.post(url, json=mismatched).status_code == 409
    bad = [imported_candidate(2), imported_candidate(1, sha256="0" * 64)]
    assert api.post(url, json=base | {"candidates": bad}).status_code == 409
    assert (
        api.post(url, json=base | {"candidates": [imported_candidate(seed=999)]}).status_code == 409
    )
    assert (
        api.post(
            url, json=base | {"candidates": [imported_candidate(source_id="wrong-receipt")]}
        ).status_code
        == 409
    )
    review = api.get("/api/v1/episodes/demo/review").json()
    (only,) = review["shots"][0]["candidates"]
    assert (
        api.post(
            f"/api/v1/artifacts/{only['artifact_id']}/decision", json={"decision": "redo"}
        ).status_code
        == 200
    )
    assert len(api.get("/api/v1/tasks").json()) == 1


def test_historical_import_is_concurrent_and_request_size_is_bounded(api, monkeypatch):
    url = "/api/v1/episodes/import"
    payload = {"episode": episode_spec(), "candidates": [imported_candidate()]}
    barrier = threading.Barrier(2)

    def run():
        barrier.wait(timeout=5)
        return api.post(url, json=payload).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        requests = [pool.submit(run) for _ in range(2)]
        assert sorted(item.result(timeout=10) for item in requests) == [200, 201]

    services = api.app.state.services
    assert services.database.scalar("SELECT count(*) FROM tasks") == 1
    assert services.database.scalar("SELECT count(*) FROM results") == 1
    assert (
        services.database.scalar("SELECT count(*) FROM event_outbox WHERE topic='episode.imported'")
        == 1
    )
    monkeypatch.setattr(history_imports, "IMPORT_LIMIT", 64)
    assert api.post(url, json=payload).status_code == 413


def test_history_does_not_extend_ordinary_episode_or_reserve_general_keys(api):
    spec = episode_spec()
    generated = api.post("/api/v1/episodes", json=spec)
    assert generated.status_code == 201
    created = api.post(
        "/api/v1/tasks",
        json={
            "task_type": "analysis",
            "idempotency_key": "history:existing-generic-key",
        },
    )
    assert created.status_code == 201
    assert (
        api.post(
            "/api/v1/episodes/import",
            json={
                "episode": spec,
                "candidates": [imported_candidate()],
            },
        ).status_code
        == 201
    )
    repeat = api.post("/api/v1/episodes", json=spec)
    assert repeat.status_code == 200
    assert [item["task_id"] for item in repeat.json()["tasks"]] == [
        item["task_id"] for item in generated.json()["tasks"]
    ]
    (imported,) = api.get("/api/v1/episodes/demo/review").json()["shots"][0]["candidates"]
    assert imported["task_type"] == "review.imported"
    db = api.app.state.services.database
    assert (
        db.scalar("SELECT idempotency_key FROM tasks WHERE task_type = 'review.imported'") is None
    )
    assert api.post("/api/v1/tasks", json={"task_type": "review.imported"}).status_code == 422


def test_offline_choices_fill_only_pristine_candidates(api):
    endpoint = "/api/v1/episodes/import"
    original = [imported_candidate(n) for n in range(1, 5)]
    original[3]["note"] = "already reviewed note"
    body = {"episode": episode_spec(), "candidates": original}
    assert api.post(endpoint, json=body).status_code == 201
    review_url = "/api/v1/episodes/demo/review"
    first, second, _, _ = api.get(review_url).json()["shots"][0]["candidates"]
    for item in (first, second):
        # The first candidate's current decision is reset by the second pick, but its
        # previous review still excludes it from automatic offline filling.
        assert (
            api.post(
                f"/api/v1/artifacts/{item['artifact_id']}/decision",
                json={
                    "decision": "pick",
                    "note": "",
                },
            ).status_code
            == 200
        )
    pending = [
        imported_candidate(1, decision="reject"),
        imported_candidate(3, decision="reject", note="offline comment"),
        imported_candidate(4, decision="reject"),
    ]
    assert api.post(endpoint, json=body | {"candidates": pending}).json() == {
        "episode_id": "demo",
        "inserted_count": 0,
        "existing_count": 3,
    }
    filled = api.post(endpoint, json=body | {"candidates": pending, "fill_unreviewed": True})
    assert filled.status_code == 200
    assert filled.json() == {
        "episode_id": "demo",
        "inserted_count": 0,
        "existing_count": 3,
        "updated_count": 1,
        "conflict_count": 2,
    }
    candidates = api.get(review_url).json()["shots"][0]["candidates"]
    assert [(item["decision"], item["note"]) for item in candidates] == [
        (None, ""),
        ("pick", ""),
        ("reject", "offline comment"),
        (None, "already reviewed note"),
    ]
    replay = api.post(endpoint, json=body | {"candidates": pending, "fill_unreviewed": True})
    assert "updated_count" not in replay.json()
    assert replay.json()["conflict_count"] == 2
    db = api.app.state.services.database
    assert db.scalar("SELECT count(*) FROM audit_events WHERE action='artifact.decision'") == 3
    assert db.scalar("SELECT count(*) FROM event_outbox WHERE topic='episode.imported'") == 2


def test_offline_selection_cannot_displace_mac_pick(api):
    endpoint = "/api/v1/episodes/import"
    body = {
        "episode": episode_spec(),
        "candidates": [
            imported_candidate(1, decision="pick"),
            imported_candidate(2),
        ],
    }
    assert api.post(endpoint, json=body).status_code == 201
    update = api.post(
        endpoint,
        json=body
        | {
            "candidates": [imported_candidate(2, decision="pick")],
            "fill_unreviewed": True,
        },
    )
    assert update.status_code == 200
    assert update.json()["conflict_count"] == 1
    candidates = api.get("/api/v1/episodes/demo/review").json()["shots"][0]["candidates"]
    assert [item["decision"] for item in candidates] == ["pick", None]


def test_offline_choice_retry_is_concurrent_and_audited_once(api):
    endpoint = "/api/v1/episodes/import"
    body = {"episode": episode_spec(), "candidates": [imported_candidate()]}
    assert api.post(endpoint, json=body).status_code == 201
    body["fill_unreviewed"] = True
    body["candidates"][0].update(decision="pick", note="operator chose")
    barrier = threading.Barrier(2)

    def post():
        barrier.wait(timeout=5)
        return api.post(endpoint, json=body)

    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = [pool.submit(post) for _ in range(2)]
        results = [item.result(timeout=10) for item in replies]
    assert all(response.status_code == 200 for response in results)
    assert sorted(response.json().get("updated_count", 0) for response in results) == [0, 1]
    db = api.app.state.services.database
    assert db.scalar("SELECT count(*) FROM audit_events WHERE action='artifact.decision'") == 1


def test_offline_note_only_fills_empty_record_and_protects_prior_note(api):
    url = "/api/v1/episodes/import"
    body = {"episode": episode_spec(), "candidates": [imported_candidate()]}
    assert api.post(url, json=body).status_code == 201
    body["fill_unreviewed"] = True
    candidate = body["candidates"][0]
    candidate["note"] = "00:00.8 physical contact"
    assert api.post(url, json=body).json()["updated_count"] == 1
    replay = api.post(url, json=body).json()
    assert "updated_count" not in replay and "conflict_count" not in replay
    previous = candidate["note"]
    candidate["note"] = "a different note"
    assert api.post(url, json=body).json()["conflict_count"] == 1
    (item,) = api.get("/api/v1/episodes/demo/review").json()["shots"][0]["candidates"]
    assert item["decision"] is None and item["note"] == previous
    db = api.app.state.services.database
    assert db.scalar("SELECT count(*) FROM audit_events WHERE action='artifact.note'") == 1


def test_episode_chain_retry_thumbnail_and_assembly(api):
    spec = episode_spec()
    created = api.post(
        "/api/v1/episodes",
        content=yaml.safe_dump(spec, allow_unicode=True),
        headers={"Content-Type": "application/yaml"},
    )
    assert created.status_code == 201, created.text
    assert api.post("/api/v1/episodes", json=spec).status_code == 200
    tasks = created.json()["tasks"]
    assert [task["task_type"] for task in tasks] == [
        "gen.keyframe",
        "gen.video",
        "gen.foley",
    ]
    assert [task["parent_task_id"] for task in tasks[1:]] == [t["task_id"] for t in tasks[:-1]]
    assemble = "/api/v1/episodes/demo/assemble"
    assert api.post(assemble).status_code == 409
    lease_url = "/api/v1/executors/lease"
    lease = {"worker_id": "bridge", "resource_tags": ["gpu-5070ti"], "lease_seconds": 60}
    task = api.post(lease_url, json=lease).json()
    assert task["task_type"] == "gen.keyframe"
    assert api.post(lease_url, json={**lease, "worker_id": "other"}).status_code == 204
    endpoint = f"/api/v1/tasks/{task['task_id']}"
    assert (
        api.post(
            endpoint + "/fail",
            json={
                "worker_id": "bridge",
                "error": "temporary",
                "retryable": True,
                "attempt_count": 1,
            },
        ).json()["status"]
        == "Retrying"
    )
    assert api.post(lease_url, json=lease).json()["attempt_count"] == 2
    thumbnail = endpoint + "/thumbnails"
    jpg = io.BytesIO()
    Image.new("RGB", (16, 16), "#28465a").save(jpg, format="JPEG")
    form = {"worker_id": "bridge", "attempt_count": "2"}
    assert api.post(thumbnail, data=form, files={"file": b"x" * 307201}).status_code == 413
    assert api.post(thumbnail, data=form, files={"file": b"fake"}).status_code == 415
    uploaded = api.post(thumbnail, data=form, files={"file": jpg.getvalue()})
    assert uploaded.status_code == 201
    assert (
        api.post(
            endpoint + "/complete",
            json={
                "worker_id": "bridge",
                "attempt_count": 2,
                "artifacts": [media()],
                "qc": {},
                "metrics": {"seconds": 0},
            },
        ).status_code
        == 200
    )
    assert (
        api.get(endpoint + "/artifacts").json()["sheet_thumbnail_id"]
        == uploaded.json()["thumbnail_id"]
    )
    finish_gate(api)
    video = api.post(lease_url, json=lease).json()
    assert video["task_type"] == "gen.video"
    video_url = f"/api/v1/tasks/{video['task_id']}"
    assert (
        api.post(
            video_url + "/complete",
            json={
                "worker_id": "bridge",
                "artifacts": [
                    {
                        "kind": "video",
                        "path": r"C:\demo\take.mp4",
                        "sha256": "1" * 64,
                        "bytes": 100,
                        "shot_id": "S01",
                        "take": 1,
                    }
                ],
                "qc": {},
                "metrics": {"seconds": 3},
            },
        ).status_code
        == 200
    )
    finish_gate(api, jpeg=jpg.getvalue())
    (artifact,) = api.get(video_url + "/artifacts").json()["artifacts"]
    decision = f"/api/v1/artifacts/{artifact['artifact_id']}/decision"
    assert api.post(decision, json={"decision": "redo", "note": "重试"}).status_code == 200
    assert api.get("/api/v1/episodes/demo/review").json()["shots"][0]["redo_count"] == 1
    assert api.post(decision, json={"decision": "pick"}).status_code == 200
    # 此视频已提出 redo，新轮次 QC 前不能复用旧片执行合成。
    assert api.post(assemble).status_code == 409
    assert api.get("/api/v1/episodes/demo/review").json()["can_assemble"] is False


def test_failed_gate_reseeds_twice_blocks_downstream_and_marks_manual(api):
    api.post("/api/v1/episodes", json=episode_spec())
    seeds = set()
    for attempt in range(3):
        task = api.post("/api/v1/executors/lease", json=LEASE).json()
        assert task["task_type"] == "gen.keyframe"
        (seed,) = task["payload"]["jobs"]["jobs"][0]["seeds"]
        assert seed not in seeds
        seeds.add(seed)
        endpoint = f"/api/v1/tasks/{task['task_id']}"
        body = {"worker_id": "bridge", "artifacts": [media()], "qc": {}, "metrics": {"seconds": 1}}
        assert api.post(endpoint + "/complete", json=body).status_code == 200
        assert api.post(endpoint + "/complete", json=body).status_code == 200
        (item,) = api.get(endpoint + "/artifacts").json()["artifacts"]
        decision = f"/api/v1/artifacts/{item['artifact_id']}/decision"
        assert api.post(decision, json={"decision": "pick"}).status_code == 409
        gate = finish_gate(api, False)
        assert gate["status"] == "Failed"
        assert gate["error_code"] == ("QC_REGENERATING" if attempt < 2 else "QC_MANUAL_REVIEW")
    assert api.post("/api/v1/executors/lease", json=LEASE).status_code == 204
    (shot,) = api.get("/api/v1/episodes/demo/review").json()["shots"]
    assert shot["redo_count"] == 2 and shot["status"] == "待人工复核"
    assert [x["qc"]["score"] for x in shot["candidates"]] == [30, 30, 30]
    assert api.post(decision, json={"decision": "redo"}).status_code == 200
    assert api.post("/api/v1/executors/lease", json=LEASE).json()["task_type"] == "gen.keyframe"


@pytest.mark.parametrize("stage", ["gen.keyframe", "gen.video"])
def test_explicit_human_override_pins_only_reviewed_inputs(api, stage):
    spec = episode_spec()
    spec["shots"][0]["last_frame"] = {"refs": [], "prompt": "closing"}
    api.post("/api/v1/episodes", json=spec)

    def lease():
        return api.post("/api/v1/executors/lease", json=LEASE)

    def complete(task, items):
        return api.post(
            f"/api/v1/tasks/{task['task_id']}/complete",
            json={"worker_id": "bridge", "artifacts": items, "qc": {}, "metrics": {"seconds": 1}},
        )

    def decide(item, **flags):
        return api.post(
            f"/api/v1/artifacts/{item['artifact_id']}/decision", json={"decision": "pick", **flags}
        )

    frames = [
        {**media(digest="1"), "path": "S01_first_v1.png"},
        {**media(digest="2"), "path": "S01_last_v1.png"},
        {**media(digest="3", take=2), "path": "S01_first_v2.png"},
        {**media(digest="4"), "path": "other_first_v1.png"},
    ]
    videos = [media("video", "5"), media("video", "6", take=2)]
    if stage == "gen.video":
        assert complete(lease().json(), frames).is_success
        finish_gate(api)
    for _ in range(3):
        source = lease().json()
        assert source["task_type"] == stage
        assert complete(source, frames if stage == "gen.keyframe" else videos).is_success
        gate = finish_gate(api, False)
    path = f"/api/v1/tasks/{source['task_id']}/artifacts"
    items = api.get(path).json()["artifacts"]
    assert decide(items[0]).status_code == 409
    chosen = [items[2], items[1]] if stage == "gen.keyframe" else [items[1]]
    if stage == "gen.keyframe":
        assert decide(items[3], accept_qc_failure=True).status_code == 409
        assert decide(items[0], accept_qc_failure=True).status_code == 200
        assert lease().status_code == 204
    for index, item in enumerate(chosen):
        assert decide(item, accept_qc_failure=True).status_code == 200
        if index + 1 < len(chosen):
            assert lease().status_code == 204
    assert decide(chosen[-1], accept_qc_failure=True).status_code == 200
    assert decide(items[0], accept_qc_failure=True).status_code == 409
    next_task = lease().json()
    pinned = next_task["payload"]["jobs"]["reviewed_inputs"]
    assert {item["artifact_id"] for item in pinned} == {item["artifact_id"] for item in chosen}
    assert {item["sha256"] for item in pinned} == {item["sha256"] for item in chosen}
    assert next_task["task_type"] == ("gen.video" if stage == "gen.keyframe" else "gen.foley")
    assert api.get(f"/api/v1/tasks/{gate['task_id']}").json()["status"] == "Failed"
    assert api.get(f"/api/v1/tasks/{gate['task_id']}/artifacts").json()["qc"]["passed"] is False
    review = api.get("/api/v1/episodes/demo/review").json()
    assert review["can_assemble"] is False  # 普通设备的人工豁免不等于可信 Owner 最终合成授权。
    records = [r for r in review["shots"][0]["candidates"] if r["task_id"] == source["task_id"]]
    assert {r["artifact_id"] for r in records if r["qc"]["human_confirmed"]} == {
        i["artifact_id"] for i in chosen
    }
    db = api.app.state.services.database
    assert db.scalar(
        "SELECT count(*) FROM audit_events WHERE reason_code='QC_HUMAN_OVERRIDE'"
    ) >= len(chosen)


def test_passing_redo_releases_correct_video_and_candidate_thumbnail(api):
    stages = api.post("/api/v1/episodes", json=episode_spec()).json()["tasks"]
    body = {"worker_id": "bridge", "artifacts": [media()], "qc": {}, "metrics": {"seconds": 1}}
    first = api.post("/api/v1/executors/lease", json=LEASE).json()
    assert api.post(f"/api/v1/tasks/{first['task_id']}/complete", json=body).is_success
    finish_gate(api, False)
    redo = api.post("/api/v1/executors/lease", json=LEASE).json()
    body["artifacts"] = [media(digest="1")]
    assert api.post(f"/api/v1/tasks/{redo['task_id']}/complete", json=body).is_success
    gate = api.post("/api/v1/executors/lease", json=LEASE).json()
    assert gate["payload"]["jobs"]["source_task_id"] == redo["task_id"]
    endpoint = f"/api/v1/tasks/{gate['task_id']}"
    jpg = io.BytesIO()
    Image.new("RGB", (16, 16), "blue").save(jpg, format="JPEG")
    thumbnails = []
    for fields in ({}, {"artifact_sha256": "1" * 64}):
        reply = api.post(
            endpoint + "/thumbnails",
            data={"worker_id": "bridge", **fields},
            files={"file": jpg.getvalue()},
        )
        thumbnails.append(reply.json()["thumbnail_id"])
    report = {"score": 90, "passed": True, "fails": []}
    body["artifacts"] = []
    body["qc"] = {**report, "by_sha256": {"1" * 64: report}}
    bad = {**body, "qc": {**report, "by_sha256": {}}}
    assert api.post(endpoint + "/complete", json=bad).status_code == 409
    assert api.post(endpoint + "/complete", json=body).status_code == 200
    next_task = api.post("/api/v1/executors/lease", json=LEASE).json()
    assert next_task["task_id"] == stages[1]["task_id"]
    assert next_task["parent_task_id"] == redo["task_id"]
    assert (
        api.get(f"/api/v1/tasks/{next_task['task_id']}/artifacts").json()["upstream_task_id"]
        == redo["task_id"]
    )
    old, current = api.get("/api/v1/episodes/demo/review").json()["shots"][0]["candidates"]
    assert old["qc"]["gate_status"] == "QC_REGENERATING"
    assert current["qc"]["report_thumbnail_id"] == thumbnails[1] != thumbnails[0]
    assert current["qc"]["report_task_id"] == gate["task_id"]


def test_assembly_uses_audio_from_selected_generation_and_take(api):
    stages = api.post("/api/v1/episodes", json=episode_spec()).json()["tasks"]
    for stage, artifacts in zip(
        stages,
        (
            [media()],
            [media("video", "1"), media("video", "2", 2)],
            [media("audio", "3"), media("audio", "4", 2)],
        ),
        strict=True,
    ):
        task = api.post("/api/v1/executors/lease", json=LEASE).json()
        assert stage["task_id"] == task["task_id"]
        qc = (
            {"foley_by_sha256": {"3" * 64: "1" * 64, "4" * 64: "2" * 64}}
            if task["task_type"] == "gen.foley"
            else {}
        )
        body = {"worker_id": "bridge", "artifacts": artifacts, "qc": qc, "metrics": {"seconds": 1}}
        path = f"/api/v1/tasks/{task['task_id']}"
        assert api.post(path + "/complete", json=body).status_code == 200
        if task["task_type"] != "gen.foley":
            finish_gate(api)
        if task["task_type"] == "gen.video":
            second = api.get(path + "/artifacts").json()["artifacts"][1]["artifact_id"]
            assert (
                api.post(
                    f"/api/v1/artifacts/{second}/decision", json={"decision": "pick"}
                ).status_code
                == 200
            )
    (shot,) = api.post("/api/v1/episodes/demo/assemble").json()["payload"]["jobs"]["shots"]
    assert shot["foley_tracks"] == [{"file": "fixture-4", "sha256": "4" * 64}]


def test_episode_validation_reports_field(api):
    spec = episode_spec()
    spec["shots"][0]["camera"]["lens"] = False
    response = api.post("/api/v1/episodes", json=spec)
    assert response.status_code == 422
    assert "shots[0].camera.lens" in response.json()["error"]["message"]


def test_manual_stage_retry_preserves_lineage_and_unblocks_descendants(api):
    response = api.post("/api/v1/episodes", json=episode_spec())
    first, video, _ = response.json()["tasks"]
    lease = {"worker_id": "bridge", "resource_tags": ["gpu-5070ti"], "lease_seconds": 60}
    url = "/api/v1/executors/lease"
    complete = {"worker_id": "bridge", "artifacts": [media()], "qc": {}, "metrics": {"seconds": 0}}
    assert api.post(url, json=lease).json()["task_id"] == first["task_id"]
    assert api.post(f"/api/v1/tasks/{first['task_id']}/complete", json=complete).status_code == 200
    finish_gate(api)
    assert api.post(url, json=lease).json()["task_id"] == video["task_id"]
    endpoint = f"/api/v1/tasks/{video['task_id']}"
    assert (
        api.post(
            endpoint + "/fail",
            json={
                "worker_id": "bridge",
                "error": "test failure",
                "retryable": False,
            },
        ).json()["status"]
        == "Failed"
    )
    retry = api.post(endpoint + "/retry").json()
    assert retry["parent_task_id"] == video["task_id"]
    assert api.post(url, json=lease).json()["task_id"] == retry["task_id"]
    retried_url = f"/api/v1/tasks/{retry['task_id']}"
    assert api.get(retried_url + "/artifacts").json()["upstream_task_id"] == first["task_id"]
    complete["artifacts"] = [media("video")]
    assert api.post(retried_url + "/complete", json=complete).status_code == 200
    finish_gate(api)
    foley = api.post(url, json=lease).json()
    assert foley["task_type"] == "gen.foley"
    assert foley["parent_task_id"] == retry["task_id"]


def test_episode_cli_reports_validation_field(tmp_path, capsys):
    path = tmp_path / "episode.yaml"
    spec = episode_spec()
    path.write_text(yaml.safe_dump(spec, allow_unicode=True), encoding="utf-8")
    assert main(["episode", "validate", str(path)]) == 0
    assert "校验通过" in capsys.readouterr().out
    spec["shots"].append(spec["shots"][0].copy())
    path.write_text(yaml.safe_dump(spec, allow_unicode=True), encoding="utf-8")
    assert main(["episode", "validate", str(path)]) == 2
    assert "shots[1].shot_id" in capsys.readouterr().err


@pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="本机未安装 FFmpeg / ffprobe",
)
def test_qc_and_hard_cut_silent_color_clip(tmp_path):
    path = tmp_path / "color.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=teal:s=96x64:r=24",
            "-t",
            "1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        timeout=15,
    )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    state = {
        "stem": "demo",
        "task": {
            "timeout_seconds": 30,
            "payload": {
                "jobs": {"shot": {"seconds": 1}},
            },
        },
    }
    with Session() as session:
        bridge = Bridge(BridgeConfig("http://localhost", "fixture", tmp_path), session)
        bridge.next_heartbeat = float("inf")
        result = bridge._qc(state, [{"kind": "video", "path": str(path), "sha256": digest}])
        assert result["qc"]["by_sha256"][digest]["通过"] is True
        state["task"]["payload"]["jobs"] = {
            "edit": {"size": [96, 64], "fps": 24, "loudness_lufs": -14},
            "shots": [
                {
                    "path": str(path),
                    "sha256": digest,
                    "seconds": 1,
                    "shot_id": "S01",
                    "transition_out": {"type": "cut", "offset_s": 0},
                    "caption": None,
                    "audio": {},
                }
            ],
        }
        (output,) = bridge._assemble(state)["outputs"]
        streams = bridge._probe(state, output)["streams"]
        assert {stream["codec_type"] for stream in streams} == {"video", "audio"}


def test_expired_attempt_is_fenced_and_terminal_fail_cannot_be_leased(api):
    record = api.post(
        "/api/v1/tasks",
        json={
            "task_type": "gen.keyframe",
            "max_attempts": 2,
            "payload": {
                "episode_id": "demo",
                "shot_id": "S01",
                "runner": "run_qwen_edit.py",
                "jobs": {},
            },
        },
    ).json()
    task_id = record["task_id"]
    url = "/api/v1/executors/lease"
    lease = {"worker_id": "bridge", "resource_tags": ["gpu-5070ti"], "lease_seconds": 60}
    assert api.post(url, json=lease).json()["attempt_count"] == 1
    db = api.app.state.services.database
    db.execute(
        "UPDATE tasks SET lease_expires_at = ? WHERE task_id = ?",
        ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), task_id),
    )
    assert api.post(url, json={**lease, "resume_task_id": task_id}).json()["attempt_count"] == 2
    failure = {"worker_id": "bridge", "error": "fake error", "retryable": True}
    endpoint = f"/api/v1/tasks/{task_id}/fail"
    assert api.post(endpoint, json={**failure, "attempt_count": 1}).status_code == 409
    assert api.post(endpoint, json={**failure, "attempt_count": 2}).json()["status"] == "Failed"
    assert api.post(url, json=lease).status_code == 204


def test_fake_worker_done_after_disconnect(live_core, tmp_path):
    class Transport(Session):
        online = True
        drop_complete_response = False

        def request(self, method, url, **kwargs):
            if not self.online:
                raise ConnectionError("offline")
            response = super().request(method, url, **kwargs)
            if self.drop_complete_response and url.endswith("/complete"):
                raise ConnectionError("response lost after commit")
            return response

    root, headers = live_core
    transport = Transport()
    transport.trust_env = False
    transport.headers.update(headers)
    result = transport.post(
        f"{root}/api/v1/tasks",
        json={
            "task_type": "gen.keyframe",
            "payload": {
                "episode_id": "demo",
                "shot_id": "S01",
                "runner": "run_qwen_edit.py",
                "jobs": {"jobs": []},
                "args": [],
            },
        },
        timeout=5,
    )
    result.raise_for_status()
    task_id = result.json()["task_id"]
    config = BridgeConfig(root, "test-bridge", tmp_path / "fake-project")
    bridge = Bridge(config, transport)
    bridge.step()
    (inbox,) = (config.root / "_queue/inbox").glob("*.json")
    assert json.loads(inbox.read_text(encoding="utf-8")) == {
        "runner": "run_qwen_edit.py",
        "jobs": f"jobs_{task_id}.json",
        "args": [],
        "note": task_id,
    }
    transport.online = False
    with pytest.raises(ConnectionError):
        Bridge(config, transport).step()
    image = config.root / "frame.jpg"
    Image.new("RGB", (24, 24), "#5689a1").save(image)
    inbox.unlink()
    done = config.root / "_queue/done" / f"{inbox.stem}.result.json"
    done.write_text('{"ok":true,"seconds":1,"outputs":["frame.jpg"]}', encoding="utf-8")
    transport.online = True
    transport.drop_complete_response = True
    with pytest.raises(ConnectionError, match="response lost"):
        Bridge(config, transport).step()
    transport.drop_complete_response = False
    Bridge(config, transport).step()
    endpoint = f"{root}/api/v1/tasks/{task_id}"
    assert transport.get(endpoint, timeout=5).json()["status"] == "Completed"
    (artifact,) = transport.get(endpoint + "/artifacts", timeout=5).json()["artifacts"]
    assert artifact["sha256"] == hashlib.sha256(image.read_bytes()).hexdigest()
    assert artifact["thumbnail_id"]
    assert not list((config.root / "_queue/inbox").glob("*.json"))
    assert not bridge.journal.exists()
    # The lost completion response did not duplicate the QC gate.
    snapshot = transport.get(f"{root}/api/v1/tasks", timeout=5).json()
    (gate,) = [t for t in snapshot if t["task_type"] == "qc.check"]
    assert gate["parent_task_id"] == task_id
    Bridge(config, transport).step()
    gate_url = f"{root}/api/v1/tasks/{gate['task_id']}"
    gate_result = transport.get(gate_url, timeout=5).json()
    # 合成样片不加载 Florence-2，只有启发式视觉结果，不得通过自动 QC。
    assert gate_result["status"] == "Failed", gate_result["error_message"]
    assert gate_result["error_message"] == "质检未通过"
    # 断线和补报只能生成一个 QC gate，失败并不表示重复执行。
    snapshot_after = transport.get(f"{root}/api/v1/tasks", timeout=5).json()
    assert len([t for t in snapshot_after if t["task_type"] == "qc.check"]) == 1
    transport.close()
