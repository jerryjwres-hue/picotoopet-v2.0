from pathlib import Path

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths


def test_invalid_bearer_token_is_rejected_without_echoing_secret(tmp_path: Path) -> None:
    """错误响应不得回显提交的令牌。"""

    secret = "wrong-secret-that-must-not-leak"
    settings = AppSettings(
        paths=RuntimePaths.from_root(tmp_path / "runtime"),
        api_token="0123456789abcdef0123456789abcdef",
    )
    with TestClient(create_app(settings)) as client:
        response = client.get(
            "/api/v1/projects",
            headers={"Authorization": f"Bearer {secret}"},
        )

    assert response.status_code == 401
    assert secret not in response.text
