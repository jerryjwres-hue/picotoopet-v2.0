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
    return TestClient(create_app(settings)), {"Authorization": f"Bearer {token}"}


def test_safe_delete_is_reversible_without_rewriting_execution_status(tmp_path: Path) -> None:
    client, headers = make_client(tmp_path)
    with client:
        created = client.post(
            "/api/v1/tasks",
            headers=headers,
            json={"task_type": "analysis", "payload": {"goal": "保留结果历史"}},
        ).json()
        task_id = created["task_id"]

        hidden = client.post(f"/api/v1/tasks/{task_id}/hide", headers=headers)
        fetched_hidden = client.get(f"/api/v1/tasks/{task_id}", headers=headers)
        restored = client.post(f"/api/v1/tasks/{task_id}/restore", headers=headers)
        fetched_restored = client.get(f"/api/v1/tasks/{task_id}", headers=headers)

    assert hidden.status_code == 200
    assert hidden.json()["success"] is True
    assert hidden.json()["pending_cancel"] is False
    assert hidden.json()["task"]["status"] == "Cancelled"
    assert hidden.json()["task"]["is_hidden"] is True
    assert fetched_hidden.json()["status"] == "Cancelled"
    assert fetched_hidden.json()["is_hidden"] is True

    assert restored.status_code == 200
    assert restored.json()["task"]["status"] == "Cancelled"
    assert restored.json()["task"]["is_hidden"] is False
    assert fetched_restored.json()["status"] == "Cancelled"
    assert fetched_restored.json()["is_hidden"] is False


def test_batch_safe_delete_and_restore_returns_one_outcome_per_explicit_id(tmp_path: Path) -> None:
    client, headers = make_client(tmp_path)
    with client:
        task_ids = [
            client.post(
                "/api/v1/tasks",
                headers=headers,
                json={"task_type": "analysis", "payload": {"index": index}},
            ).json()["task_id"]
            for index in range(2)
        ]
        hidden = client.post(
            "/api/v1/tasks/batch-hide",
            headers=headers,
            json={"task_ids": task_ids},
        )
        listed_hidden = client.get("/api/v1/tasks", headers=headers).json()
        restored = client.post(
            "/api/v1/tasks/batch-restore",
            headers=headers,
            json={"task_ids": task_ids},
        )

    assert hidden.status_code == 200
    assert [item["task_id"] for item in hidden.json()["outcomes"]] == task_ids
    assert all(item["success"] for item in hidden.json()["outcomes"])
    hidden_by_id = {item["task_id"]: item for item in listed_hidden}
    assert all(hidden_by_id[task_id]["is_hidden"] is True for task_id in task_ids)

    assert restored.status_code == 200
    assert [item["task_id"] for item in restored.json()["outcomes"]] == task_ids
    assert all(item["task"]["is_hidden"] is False for item in restored.json()["outcomes"])


def test_batch_visibility_rejects_duplicate_task_ids(tmp_path: Path) -> None:
    client, headers = make_client(tmp_path)
    with client:
        task_id = client.post(
            "/api/v1/tasks",
            headers=headers,
            json={"task_type": "analysis"},
        ).json()["task_id"]
        response = client.post(
            "/api/v1/tasks/batch-hide",
            headers=headers,
            json={"task_ids": [task_id, task_id]},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
