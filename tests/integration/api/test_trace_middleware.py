"""API Trace 与 Server-Timing 中间件测试。"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths


def make_client(tmp_path: Path) -> TestClient:
    """创建隔离运行目录的测试客户端。"""

    settings = AppSettings(
        paths=RuntimePaths.from_root(tmp_path / "runtime"),
        api_token="0123456789abcdef0123456789abcdef",
    )
    return TestClient(create_app(settings))


def test_trace_id_is_generated_and_returned(tmp_path: Path) -> None:
    """未提供 Trace ID 时必须生成稳定格式并返回。"""

    with make_client(tmp_path) as client:
        response = client.get("/api/v1/health")

    trace_id = response.headers["X-Picotoo-Trace-Id"]
    assert re.fullmatch(r"[0-9a-f]{32}", trace_id)
    assert response.headers["Server-Timing"].startswith("app;dur=")


def test_supplied_trace_id_is_propagated(tmp_path: Path) -> None:
    """合法 Trace ID 必须原样贯穿请求与响应。"""

    supplied = "trace-phase2-001"
    with make_client(tmp_path) as client:
        response = client.get(
            "/api/v1/health",
            headers={"X-Picotoo-Trace-Id": supplied},
        )

    assert response.headers["X-Picotoo-Trace-Id"] == supplied
    duration = float(response.headers["Server-Timing"].split("=")[1])
    assert duration >= 0


def test_invalid_trace_id_is_replaced(tmp_path: Path) -> None:
    """超长或含控制字符的 Trace ID 不得进入日志上下文。"""

    with make_client(tmp_path) as client:
        response = client.get(
            "/api/v1/health",
            headers={"X-Picotoo-Trace-Id": "x" * 200},
        )

    assert response.headers["X-Picotoo-Trace-Id"] != "x" * 200
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Picotoo-Trace-Id"])
