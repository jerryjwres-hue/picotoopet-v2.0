"""Mac Core 本进程延迟微基准。"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.performance.percentiles import summarize_samples


def test_local_health_latency_report_is_well_formed(tmp_path: Path) -> None:
    """本地微基准必须生成完整分位数，不以单次耗时冒充验收。"""

    settings = AppSettings(
        paths=RuntimePaths.from_root(tmp_path / "runtime"),
        api_token="0123456789abcdef0123456789abcdef",
    )
    samples: list[float] = []
    with TestClient(create_app(settings)) as client:
        for _ in range(50):
            started  = time.perf_counter_ns()
            response = client.get("/api/v1/health")
            elapsed  = (time.perf_counter_ns() - started) / 1_000_000
            assert response.status_code == 200
            samples.append(elapsed)

    summary = summarize_samples(samples)

    assert summary["count"] == 50
    assert 0 <= summary["p50_ms"] <= summary["p95_ms"]
    assert summary["p95_ms"] <= summary["p99_ms"] <= summary["max_ms"]
    assert summary["p95_ms"] < 250
