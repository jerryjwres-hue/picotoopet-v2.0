"""WebSocket 事件续传与 Ping/Pong 测试。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.domain.models import TaskCreate


def make_app(tmp_path: Path):  # type: ignore[no-untyped-def]
    """创建带固定令牌的隔离应用。"""

    token = "0123456789abcdef0123456789abcdef"
    app   = create_app(
        AppSettings(paths=RuntimePaths.from_root(tmp_path / "runtime"), api_token=token)
    )
    return app, token


def test_websocket_replays_only_missing_events(tmp_path: Path) -> None:
    """客户端重连后只应收到最后确认序号之后的事件。"""

    app, token = make_app(tmp_path)
    with TestClient(app) as client:
        first  = app.state.services.queue.create(TaskCreate(task_type="analysis"))
        second = app.state.services.queue.create(TaskCreate(task_type="create_script"))
        events = app.state.services.outbox.list_after(0)
        assert [event.payload["task_id"] for event in events] == [first.task_id, second.task_id]

        with client.websocket_connect(
            f"/api/v1/events?after_sequence={events[0].sequence}",
            headers={"Authorization": f"Bearer {token}"},
        ) as websocket:
            connected = websocket.receive_json()
            replayed  = websocket.receive_json()

    assert connected["topic"] == "connected"
    assert connected["last_sequence"] == events[0].sequence
    assert replayed["sequence"] == events[1].sequence
    assert replayed["payload"]["task_id"] == second.task_id


def test_websocket_application_ping_pong(tmp_path: Path) -> None:
    """桌面端必须能使用应用级 Ping/Pong 测量活动链路。"""

    app, token = make_app(tmp_path)
    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/v1/events?after_sequence=0",
            headers={"Authorization": f"Bearer {token}"},
        ) as websocket:
            assert websocket.receive_json()["topic"] == "connected"
            websocket.send_json({"type": "ping", "nonce": "latency-001"})
            response = websocket.receive_json()

    assert response["type"] == "pong"
    assert response["nonce"] == "latency-001"
    assert response["server_time"].endswith("+00:00")
