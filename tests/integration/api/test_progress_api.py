from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.domain.models import TaskCreate
from picotoopet_core.progress.models import ProgressUpdate
from picotoopet_core.progress.repository import ProgressRepository

_TOKEN = "0123456789abcdef0123456789abcdef"
_HEADERS = {"Authorization": f"Bearer {_TOKEN}"}


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        paths=RuntimePaths.from_root(tmp_path / "runtime"),
        api_token=_TOKEN,
    )


def test_task_progress_endpoint_returns_bounded_truthful_snapshot(tmp_path: Path) -> None:
    """Windows 只能读取 Core 的持久进度，不得由客户端估算百分比。"""

    app = create_app(_settings(tmp_path))
    task = app.state.services.queue.create(TaskCreate(task_type="system.noop"))
    repository = ProgressRepository(app.state.services.database)
    repository.append(
        ProgressUpdate(
            task_id=task.task_id,
            stage="research-search",
            completed=2,
            total=6,
            message="搜索 2/6 完成",
            component="research",
            details={"successful_sources": 2, "failed_sources": 0},
        )
    )

    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/tasks/{task.task_id}/progress",
            headers=_HEADERS,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == task.task_id
    assert body["stage"] == "research-search"
    assert body["completed"] == 2
    assert body["total"] == 6
    assert body["percent"] == 33.33
    assert body["latest_message"] == "搜索 2/6 完成"
    assert body["component"] == "research"
    assert len(body["recent_events"]) == 1


def test_task_progress_endpoint_requires_authentication(tmp_path: Path) -> None:
    """进度包含内部执行事实，必须沿用 Control Center 设备认证。"""

    app = create_app(_settings(tmp_path))
    task = app.state.services.queue.create(TaskCreate(task_type="system.noop"))

    with TestClient(app) as client:
        response = client.get(f"/api/v1/tasks/{task.task_id}/progress")

    assert response.status_code == 401


def test_task_progress_endpoint_returns_not_found_for_unknown_task(tmp_path: Path) -> None:
    """不存在的任务不能返回伪造的空进度。"""

    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.get(
            "/api/v1/tasks/missing-task/progress",
            headers=_HEADERS,
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TASK_NOT_FOUND"
