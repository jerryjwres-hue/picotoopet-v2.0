from pathlib import Path

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths


def make_client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    token = "0123456789abcdef0123456789abcdef"
    settings = AppSettings(paths=RuntimePaths.from_root(tmp_path / "runtime"), api_token=token)
    client = TestClient(create_app(settings))
    return client, {"Authorization": f"Bearer {token}"}


def test_health_is_public_but_business_routes_require_auth(tmp_path: Path) -> None:
    """健康检查可被局域网探测，业务接口必须认证。"""

    client, headers = make_client(tmp_path)
    with client:
        health = client.get("/api/v1/health")
        denied = client.get("/api/v1/projects")
        allowed = client.get("/api/v1/projects", headers=headers)

    assert health.status_code == 200
    assert health.json()["status"] in {"ok", "degraded"}
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
    assert allowed.status_code == 200


def test_project_and_task_creation_are_durable_and_idempotent(tmp_path: Path) -> None:
    """REST 创建项目和任务后必须落入 SQLite，并支持幂等键。"""

    client, headers = make_client(tmp_path)
    with client:
        project = client.post(
            "/api/v1/projects",
            headers=headers,
            json={
                "title": "真实宠物短视频",
                "project_type": "content",
                "source_app": "creator-assistant",
                "classification": "INTERNAL",
            },
        )
        project_id = project.json()["project_id"]
        payload = {
            "project_id": project_id,
            "task_type": "create_script",
            "payload": {"topic": "猫咪喝水"},
        }
        first = client.post(
            "/api/v1/tasks",
            headers={**headers, "Idempotency-Key": "task-001"},
            json=payload,
        )
        second = client.post(
            "/api/v1/tasks",
            headers={**headers, "Idempotency-Key": "task-001"},
            json=payload,
        )
        fetched = client.get(f"/api/v1/tasks/{first.json()['task_id']}", headers=headers)

    assert project.status_code == 201
    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["task_id"] == first.json()["task_id"]
    assert fetched.json()["status"] == "Queued"


def test_cloud_task_waits_for_approval_and_can_be_cancelled(tmp_path: Path) -> None:
    """云端策略必须等待批准，取消后不得继续运行。"""

    client, headers = make_client(tmp_path)
    with client:
        created = client.post(
            "/api/v1/tasks",
            headers=headers,
            json={"task_type": "cloud_upload", "cloud_policy": "cloud_manual"},
        )
        task_id = created.json()["task_id"]
        cancelled = client.post(f"/api/v1/tasks/{task_id}/cancel", headers=headers)

    assert created.json()["status"] == "WaitingForApproval"
    assert cancelled.json()["status"] == "Cancelled"


def test_task_list_retry_and_approval_rejection_routes(tmp_path: Path) -> None:
    """任务列表、子任务重试和审批拒绝必须通过统一 API 完成。"""

    client, headers = make_client(tmp_path)
    with client:
        local = client.post(
            "/api/v1/tasks",
            headers=headers,
            json={"task_type": "analysis", "payload": {"source": "test"}},
        ).json()
        client.post(f"/api/v1/tasks/{local['task_id']}/cancel", headers=headers)
        retried = client.post(f"/api/v1/tasks/{local['task_id']}/retry", headers=headers)
        listed = client.get("/api/v1/tasks", headers=headers)

        cloud = client.post(
            "/api/v1/tasks",
            headers=headers,
            json={"task_type": "cloud_upload", "cloud_policy": "cloud_manual"},
        ).json()
        grant = client.post(
            "/api/v1/approvals",
            headers=headers,
            json={
                "task_id": cloud["task_id"],
                "approval_type": "cloud_upload",
                "scope": {"file": "handoff.zip"},
            },
        ).json()
        rejected = client.post(
            f"/api/v1/approvals/{grant['approval_id']}/reject",
            headers=headers,
            json={"token": grant["token"], "reason": "owner rejected"},
        )

    assert retried.status_code == 200
    assert retried.json()["parent_task_id"] == local["task_id"]
    assert len(listed.json()) >= 2
    assert rejected.json()["status"] == "Rejected"


def test_status_and_audit_verify_routes(tmp_path: Path) -> None:
    """状态与审计完整性接口必须返回可验证结构。"""

    client, headers = make_client(tmp_path)
    with client:
        status_response = client.get("/api/v1/status", headers=headers)
        audit_response = client.get("/api/v1/audit/verify", headers=headers)

    assert status_response.status_code == 200
    assert "task_counts" in status_response.json()
    assert audit_response.status_code == 200
    assert audit_response.json()["valid"] is True


def test_validation_errors_use_standard_error_envelope(tmp_path: Path) -> None:
    """Pydantic 校验失败必须使用统一错误结构。"""

    client, headers = make_client(tmp_path)
    with client:
        response = client.post(
            "/api/v1/tasks",
            headers=headers,
            json={"task_type": "", "priority": -1},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["retryable"] is False


def test_invalid_task_transition_uses_conflict_error_envelope(tmp_path: Path) -> None:
    """重复取消终态任务必须返回统一 CONFLICT，而不是 500。"""

    client, headers = make_client(tmp_path)
    with client:
        task = client.post(
            "/api/v1/tasks",
            headers=headers,
            json={"task_type": "analysis"},
        ).json()
        client.post(f"/api/v1/tasks/{task['task_id']}/cancel", headers=headers)
        response = client.post(f"/api/v1/tasks/{task['task_id']}/cancel", headers=headers)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"
    assert response.json()["error"]["retryable"] is False


def test_invalid_approval_token_uses_conflict_error_envelope(tmp_path: Path) -> None:
    """无效人工审批令牌必须返回统一 CONFLICT，而不是泄露内部异常。"""

    client, headers = make_client(tmp_path)
    with client:
        cloud = client.post(
            "/api/v1/tasks",
            headers=headers,
            json={"task_type": "cloud_upload", "cloud_policy": "cloud_manual"},
        ).json()
        grant = client.post(
            "/api/v1/approvals",
            headers=headers,
            json={
                "task_id": cloud["task_id"],
                "approval_type": "cloud_upload",
                "scope": {"file": "handoff.zip"},
            },
        ).json()
        response = client.post(
            f"/api/v1/approvals/{grant['approval_id']}/approve",
            headers=headers,
            json={"token": "invalid-token", "reason": "invalid"},
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"
    assert response.json()["error"]["retryable"] is False


def test_retrying_active_task_uses_conflict_error_envelope(tmp_path: Path) -> None:
    """活跃任务不可重试，必须返回统一 CONFLICT。"""

    client, headers = make_client(tmp_path)
    with client:
        task = client.post(
            "/api/v1/tasks",
            headers=headers,
            json={"task_type": "analysis"},
        ).json()
        response = client.post(f"/api/v1/tasks/{task['task_id']}/retry", headers=headers)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"
    assert response.json()["error"]["retryable"] is False
