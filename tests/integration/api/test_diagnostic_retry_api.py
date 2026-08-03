"""Slice D 诊断重试 HTTP 边界的幂等和活动去重回归。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths


def make_client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    token = "0123456789abcdef0123456789abcdef"
    settings = AppSettings(
        paths=RuntimePaths.from_root(tmp_path / "runtime"),
        api_token=token,
    )
    return (
        TestClient(create_app(settings)),
        {"Authorization": f"Bearer {token}"},
    )


def create_diagnostic(
    client: TestClient,
    headers: dict[str, str],
    key: str,
) -> dict[str, object]:
    response = client.post(
        "/api/v1/tasks/system-diagnostic-snapshot",
        headers={**headers, "Idempotency-Key": key},
        json={"schema_version": "1.0", "sections": ["core"]},
    )
    assert response.status_code == 201
    return response.json()


def test_retry_replay_returns_same_child_task(tmp_path: Path) -> None:
    client, headers = make_client(tmp_path)
    with client:
        original = create_diagnostic(client, headers, "retry-original")
        cancelled = client.post(
            f"/api/v1/tasks/{original['task_id']}/cancel",
            headers=headers,
        )
        first = client.post(
            f"/api/v1/tasks/{original['task_id']}/retry",
            headers=headers,
        )
        replay = client.post(
            f"/api/v1/tasks/{original['task_id']}/retry",
            headers=headers,
        )
        rows = client.app.state.services.database.fetchall(
            "SELECT task_id, parent_task_id, idempotency_key, dedupe_key "
            "FROM tasks ORDER BY rowid"
        )

    assert cancelled.status_code == 200
    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json()["task_id"] == first.json()["task_id"]
    assert len(rows) == 2
    assert rows[1]["parent_task_id"] == original["task_id"]
    assert rows[1]["idempotency_key"] == f"retry:{original['task_id']}"
    assert rows[1]["dedupe_key"] == "system-diagnostic:active"


def test_retry_returns_existing_active_diagnostic(tmp_path: Path) -> None:
    client, headers = make_client(tmp_path)
    with client:
        original = create_diagnostic(client, headers, "dedupe-original")
        client.post(
            f"/api/v1/tasks/{original['task_id']}/cancel",
            headers=headers,
        )
        active = create_diagnostic(client, headers, "dedupe-active")
        retried = client.post(
            f"/api/v1/tasks/{original['task_id']}/retry",
            headers=headers,
        )
        count = client.app.state.services.database.scalar(
            "SELECT COUNT(*) FROM tasks"
        )

    assert retried.status_code == 200
    assert retried.json()["task_id"] == active["task_id"]
    assert count == 2
