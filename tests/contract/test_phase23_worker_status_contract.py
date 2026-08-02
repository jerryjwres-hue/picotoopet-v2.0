from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths

_TOKEN = "0123456789abcdef0123456789abcdef"
_HEADERS = {"Authorization": f"Bearer {_TOKEN}"}


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        paths=RuntimePaths.from_root(tmp_path / "runtime"),
        api_token=_TOKEN,
    )


def test_worker_status_is_truthful_when_worker_is_not_started(tmp_path: Path) -> None:
    """没有状态快照时必须显式报告 not_deployed，不能伪造在线。"""

    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.get("/api/v1/workers/status", headers=_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "2.3.0"
    assert body["available"] is False
    assert body["state"] == "not_deployed"
    assert body["reason"] == "worker_runtime_not_installed"
    assert body["worker_id"] is None
    assert body["supported_task_types"] == []
    assert body["active_task_id"] is None
    assert body["last_heartbeat_at"] is None
    observed_at = datetime.fromisoformat(body["observed_at"].replace("Z", "+00:00"))
    assert observed_at.tzinfo is not None
    assert observed_at.astimezone(UTC) <= datetime.now(UTC)


def test_capabilities_advertise_worker_binary_without_faking_online_state(
    tmp_path: Path,
) -> None:
    """本地 Worker 能力存在不代表进程在线。"""

    with TestClient(create_app(_settings(tmp_path))) as client:
        capability_response = client.get("/api/v1/capabilities")
        status_response = client.get("/api/v1/workers/status", headers=_HEADERS)

    assert capability_response.status_code == 200
    features = capability_response.json()["features"]
    assert features["worker_status"] is True
    assert features["local_worker"] is True
    assert status_response.json()["state"] == "not_deployed"


def test_worker_status_endpoint_reads_atomic_runtime_snapshot(tmp_path: Path) -> None:
    """状态路由必须读取 Worker 写入的快照。"""

    app = create_app(_settings(tmp_path))
    app.state.services.worker_state.publish(
        state="online",
        reason="idle",
        worker_id="worker-m4",
        supported_task_types=("system.noop",),
        active_task_id=None,
    )
    with TestClient(app) as client:
        response = client.get("/api/v1/workers/status", headers=_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["state"] == "online"
    assert body["reason"] == "idle"
    assert body["worker_id"] == "worker-m4"
    assert body["supported_task_types"] == ["system.noop"]
