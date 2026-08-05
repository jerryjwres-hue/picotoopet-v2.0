from pathlib import Path

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths


def make_client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    token = "0123456789abcdef0123456789abcdef"
    settings = AppSettings(paths=RuntimePaths.from_root(tmp_path / "runtime"), api_token=token)
    return TestClient(create_app(settings)), {"Authorization": f"Bearer {token}"}


def test_approval_center_list_and_idempotent_owner_decision(tmp_path: Path) -> None:
    """Windows 审批中心只使用摘要和幂等键，不接收一次性明文令牌。"""

    client, headers = make_client(tmp_path)
    with client:
        task = client.post(
            "/api/v1/tasks",
            headers=headers,
            json={"task_type": "cloud_upload", "cloud_policy": "cloud_manual"},
        ).json()
        client.post(
            "/api/v1/approvals",
            headers=headers,
            json={
                "task_id": task["task_id"],
                "approval_type": "cloud_upload",
                "scope": {"target": "approved-handoff.zip", "budget": 0},
            },
        )

        listed = client.get("/api/v1/approvals?limit=50", headers=headers)
        item = listed.json()[0]
        decision_headers = {**headers, "Idempotency-Key": "approval-ui-click-001"}
        approved = client.post(
            f"/api/v1/approvals/{item['approval_id']}/decision",
            headers=decision_headers,
            json={
                "decision": "approve",
                "request_digest": item["request_digest"],
                "reason": "批准固定目标",
            },
        )
        replay = client.post(
            f"/api/v1/approvals/{item['approval_id']}/decision",
            headers=decision_headers,
            json={
                "decision": "approve",
                "request_digest": item["request_digest"],
                "reason": "批准固定目标",
            },
        )

    assert listed.status_code == 200
    assert item["status"] == "Pending"
    assert len(item["request_digest"]) == 64
    assert "token" not in listed.text.lower()
    assert approved.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == approved.json()


def test_approval_center_decision_requires_idempotency_key(tmp_path: Path) -> None:
    """缺少幂等键的审批决策必须在产生副作用前拒绝。"""

    client, headers = make_client(tmp_path)
    with client:
        task = client.post(
            "/api/v1/tasks",
            headers=headers,
            json={"task_type": "cloud_upload", "cloud_policy": "cloud_manual"},
        ).json()
        client.post(
            "/api/v1/approvals",
            headers=headers,
            json={"task_id": task["task_id"], "approval_type": "cloud_upload"},
        )
        item = client.get("/api/v1/approvals", headers=headers).json()[0]
        response = client.post(
            f"/api/v1/approvals/{item['approval_id']}/decision",
            headers=headers,
            json={
                "decision": "reject",
                "request_digest": item["request_digest"],
                "reason": "缺少幂等键",
            },
        )

    assert response.status_code == 422
