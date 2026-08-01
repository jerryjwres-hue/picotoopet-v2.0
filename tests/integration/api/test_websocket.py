from pathlib import Path

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths


def test_authenticated_websocket_receives_broker_event(tmp_path: Path) -> None:
    """通过认证的桌面面板必须收到 Mac Core 广播事件。"""

    token = "0123456789abcdef0123456789abcdef"
    settings = AppSettings(paths=RuntimePaths.from_root(tmp_path / "runtime"), api_token=token)
    app = create_app(settings)
    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/v1/events",
            headers={"Authorization": f"Bearer {token}"},
        ) as websocket:
            assert websocket.receive_json()["topic"] == "connected"
            client.portal.call(
                app.state.services.broker.publish,
                {"topic": "task.updated", "task_id": "task-1"},
            )
            assert websocket.receive_json() == {"topic": "task.updated", "task_id": "task-1"}


def test_websocket_rejects_invalid_token(tmp_path: Path) -> None:
    """无效设备令牌不得订阅内部事件。"""

    settings = AppSettings(
        paths=RuntimePaths.from_root(tmp_path / "runtime"),
        api_token="0123456789abcdef0123456789abcdef",
    )
    with TestClient(create_app(settings)) as client:
        try:
            with client.websocket_connect(
                "/api/v1/events",
                headers={"Authorization": "Bearer invalid"},
            ):
                raise AssertionError("无效令牌不应连接成功。")
        except WebSocketDisconnect as exc:
            assert exc.code == 4401
