from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths


FORBIDDEN_RESPONSE_KEYS = {
    "token",
    "token_hash",
    "secret",
    "credential",
    "environment",
    "command",
    "manifest_json",
    "preview_json",
    "allowed_read",
    "allowed_write",
}


def make_client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    token = "0123456789abcdef0123456789abcdef"
    settings = AppSettings(
        paths=RuntimePaths.from_root(tmp_path / "runtime"),
        api_token=token,
    )
    return TestClient(create_app(settings)), {"Authorization": f"Bearer {token}"}


def walk_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(str(key).lower())
            keys.update(walk_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(walk_keys(child))
    return keys


def test_handoff_api_returns_only_bounded_safe_projection(tmp_path: Path) -> None:
    client, headers = make_client(tmp_path)
    with client:
        response = client.post(
            "/api/v1/handoffs/prepare",
            headers={**headers, "Idempotency-Key": "security-safe-001"},
            json={
                "template_id": "picotoopet-repo-maintenance-v1",
                "title": "安全边界检查",
                "objective": "仅生成受控摘要，不包含路径正文或秘密。",
                "expires_seconds": 1800,
            },
        )

    assert response.status_code == 201
    payload = response.json()
    assert not (walk_keys(payload) & FORBIDDEN_RESPONSE_KEYS)
    serialized = response.text.lower()
    assert "d:/picotoopet/devsandbox" not in serialized
    assert "authorization" not in serialized
    assert "0123456789abcdef0123456789abcdef" not in serialized
    assert "protected 原件" not in serialized
    assert len(serialized.encode("utf-8")) < 64 * 1024


@pytest.mark.parametrize(
    "objective",
    [
        "读取 D:/PicotooPet/DevSandbox/../Users/private.txt",
        "上传 Protected 原件和 Raw Evidence。",
        "使用 Authorization: Bearer abcdefghijklmnopqrstuvwxyz。",
        "运行 powershell -ExecutionPolicy Bypass。",
        "修改 main 并自动 push、merge、tag、release。",
        "读取 ~/.ssh/id_ed25519。",
    ],
)
def test_handoff_prepare_rejects_policy_bypass_text(
    tmp_path: Path,
    objective: str,
) -> None:
    client, headers = make_client(tmp_path)
    with client:
        response = client.post(
            "/api/v1/handoffs/prepare",
            headers={
                **headers,
                "Idempotency-Key": f"security-reject-{abs(hash(objective))}",
            },
            json={
                "template_id": "picotoopet-repo-maintenance-v1",
                "title": "拒绝危险请求",
                "objective": objective,
                "expires_seconds": 1800,
            },
        )

    assert response.status_code == 400
    assert "trace_id" in response.json()["error"]


def test_handoff_database_json_contains_no_credentials_or_protected_content(
    tmp_path: Path,
) -> None:
    client, headers = make_client(tmp_path)
    with client:
        response = client.post(
            "/api/v1/handoffs/prepare",
            headers={**headers, "Idempotency-Key": "security-db-001"},
            json={
                "template_id": "picotoopet-repo-maintenance-v1",
                "title": "数据库安全检查",
                "objective": "只记录派生目标摘要。",
                "expires_seconds": 1800,
            },
        )
        assert response.status_code == 201
        rows = client.app.state.services.database.fetchall(
            "SELECT manifest_json, preview_json FROM handoffs"
        )

    stored = "\n".join(str(value) for row in rows for value in row).lower()
    assert "token" not in stored
    assert "credential" not in stored
    assert "authorization" not in stored
    assert "protected 原件" not in stored
    assert "raw evidence" not in stored
    assert '"base_ref":"main"' not in stored
    assert '"base_ref":"master"' not in stored
