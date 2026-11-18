import hashlib
import io
import json
import secrets
import socket
import threading
from datetime import UTC, datetime, timedelta

import pytest
import uvicorn
import yaml
from fastapi.testclient import TestClient
from PIL import Image
from requests import ConnectionError, Session

from picotoopet_core.api.app import create_app
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
    decision_url = f"/api/v1/artifacts/{artifact['artifact_id']}/decision"
    assert api.post(decision_url, json={"decision": "pick", "note": "演示"}).status_code == 200
    assert api.get(endpoint + "/artifacts").json()["artifacts"][0]["decision"] == "pick"
    services = api.app.state.services
    assert verify_audit_chain(services.database).valid
    assert (
        services.database.scalar(
            "SELECT COUNT(*) FROM audit_events WHERE action='executor.complete'"
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
        "qc.check",
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
                "artifacts": [],
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
    (artifact,) = api.get(video_url + "/artifacts").json()["artifacts"]
    decision = f"/api/v1/artifacts/{artifact['artifact_id']}/decision"
    assert api.post(decision, json={"decision": "redo", "note": "重试"}).status_code == 200
    assert api.get("/api/v1/episodes/demo/review").json()["shots"][0]["redo_count"] == 1
    assert api.post(decision, json={"decision": "pick"}).status_code == 200
    assembly = api.post(assemble).json()
    assert assembly["task_type"] == "edit.assemble"
    assert api.post(assemble).json()["task_id"] == assembly["task_id"]


def test_episode_validation_reports_field(api):
    spec = episode_spec()
    spec["shots"][0]["camera"]["lens"] = False
    response = api.post("/api/v1/episodes", json=spec)
    assert response.status_code == 422
    assert "shots[0].camera.lens" in response.json()["error"]["message"]


def test_manual_stage_retry_preserves_lineage_and_unblocks_descendants(api):
    response = api.post("/api/v1/episodes", json=episode_spec())
    first, video, _, _ = response.json()["tasks"]
    lease = {"worker_id": "bridge", "resource_tags": ["gpu-5070ti"], "lease_seconds": 60}
    url = "/api/v1/executors/lease"
    complete = {"worker_id": "bridge", "artifacts": [], "qc": {}, "metrics": {"seconds": 0}}
    assert api.post(url, json=lease).json()["task_id"] == first["task_id"]
    assert api.post(f"/api/v1/tasks/{first['task_id']}/complete", json=complete).status_code == 200
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
    assert api.post(retried_url + "/complete", json=complete).status_code == 200
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


@pytest.fixture
def live_core(tmp_path):
    token = secrets.token_hex(24)
    app = create_app(AppSettings(paths=RuntimePaths.from_root(tmp_path / "core"), api_token=token))
    server = uvicorn.Server(uvicorn.Config(app, ws="none", log_level="warning"))
    # Reserve a loopback socket first so concurrent tests cannot reuse the chosen port.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{port}", {"Authorization": f"Bearer {token}"}
        finally:
            server.should_exit = True
            thread.join(timeout=5)
            assert not thread.is_alive()


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
    # Startup is asynchronous, but the listening port was reserved by the fixture.
    import time

    for _ in range(50):
        try:
            transport.get(f"{root}/api/v1/health", timeout=1).raise_for_status()
            break
        except ConnectionError:
            time.sleep(0.05)
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
    transport.close()
