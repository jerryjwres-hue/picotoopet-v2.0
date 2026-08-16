"""Research Gateway 搜索任务的固定创建与结果 API 契约。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths


def make_client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    # 测试隔离：每个用例使用独立 RuntimePaths 与固定测试令牌。
    token = "0123456789abcdef0123456789abcdef"
    settings = AppSettings(
        paths=RuntimePaths.from_root(tmp_path / "runtime"),
        api_token=token,
    )
    return TestClient(create_app(settings)), {"Authorization": f"Bearer {token}"}


def test_windows_generic_research_request_is_strictly_frozen(tmp_path: Path) -> None:
    client, headers = make_client(tmp_path)
    with client:
        # Windows 复用现有 tasks.create，但服务端覆盖所有执行参数，不能扩大权限。
        created = client.post(
            "/api/v1/tasks",
            headers={**headers, "Idempotency-Key": "research-openai-001"},
            json={
                "task_type": "research.search",
                "payload": {"query": "OpenAI", "limit": 5},
                "priority": 999,
                "resource_tag": "arbitrary",
                "max_attempts": 20,
                "timeout_seconds": 86400,
                "cloud_policy": "cloud_manual",
            },
        )
        missing_key = client.post(
            "/api/v1/tasks",
            headers=headers,
            json={"task_type": "research.search", "payload": {"query": "OpenAI"}},
        )

    assert missing_key.status_code == 422
    assert created.status_code == 201
    body = created.json()
    assert body["task_type"] == "research.search"
    assert body["payload"] == {"schema_version": "1.0", "query": "OpenAI", "limit": 5}
    assert body["priority"] == 60
    assert body["resource_tag"] == "research-gateway"
    assert body["max_attempts"] == 2
    assert body["timeout_seconds"] == 120
    assert body["status"] == "Queued"


def test_research_search_payload_is_strict_and_bounded(tmp_path: Path) -> None:
    client, headers = make_client(tmp_path)
    invalid = [
        {"query": "", "limit": 5},
        {"query": "x" * 501, "limit": 5},
        {"query": "OpenAI", "limit": 0},
        {"query": "OpenAI", "limit": 21},
        {"query": "OpenAI", "limit": 5, "command": "rm -rf ~"},
    ]
    with client:
        responses = [
            client.post(
                "/api/v1/tasks",
                headers={**headers, "Idempotency-Key": f"research-invalid-{index}"},
                json={"task_type": "research.search", "payload": payload},
            )
            for index, payload in enumerate(invalid)
        ]

    assert [response.status_code for response in responses] == [422, 422, 422, 422, 422]


def test_research_result_uses_existing_result_store_with_fixed_type(tmp_path: Path) -> None:
    client, headers = make_client(tmp_path)
    with client:
        created = client.post(
            "/api/v1/tasks/research-search",
            headers={**headers, "Idempotency-Key": "research-result-001"},
            json={"query": "OpenAI", "limit": 3},
        ).json()
        services = client.app.state.services
        leased = services.queue.lease_next(
            "worker-research",
            supported_task_types=("research.search",),
        )
        assert leased is not None
        stored = services.results.put_json(
            {
                "schema_version": "1.0",
                "capability": "research.search",
                "query": "OpenAI",
                "limit": 3,
                "output": "result-a\nresult-b",
            },
            result_type="research.search",
            max_bytes=64 * 1024,
        )
        completed = services.queue.complete_leased_with_result(
            created["task_id"],
            worker_id="worker-research",
            stored_result=stored,
            schema_version="1.0",
        )
        response = client.get(
            f"/api/v1/tasks/{created['task_id']}/result",
            headers=headers,
        )

    assert completed.result_id is not None
    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "1.0",
        "capability": "research.search",
        "query": "OpenAI",
        "limit": 3,
        "output": "result-a\nresult-b",
    }
