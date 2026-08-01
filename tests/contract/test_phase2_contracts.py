"""Phase 2 事件与性能契约测试。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_event_envelope_schema_has_resume_fields() -> None:
    """事件契约必须包含顺序号、事件标识、时间和负载。"""

    schema = json.loads((ROOT / "contracts/schemas/event_envelope_v2.schema.json").read_text())

    assert schema["$id"] == "https://picotoopet.local/schemas/event_envelope_v2.schema.json"
    assert set(schema["required"]) == {
        "schema_version",
        "sequence",
        "event_id",
        "topic",
        "created_at",
        "payload",
    }
    assert schema["properties"]["sequence"]["minimum"] == 1
    assert schema["properties"]["payload"]["type"] == "object"


def test_performance_report_schema_requires_percentiles() -> None:
    """性能报告不得只提供平均值，必须包含分位数和最大值。"""

    schema = json.loads((ROOT / "contracts/schemas/performance_report_v2.schema.json").read_text())
    metric = schema["$defs"]["metric"]

    assert set(schema["required"]) == {
        "schema_version",
        "generated_at",
        "status",
        "environment",
        "metrics",
        "errors",
    }
    assert set(metric["required"]) == {
        "count",
        "p50_ms",
        "p95_ms",
        "p99_ms",
        "max_ms",
        "p95_limit_ms",
        "p99_limit_ms",
        "passed",
    }
    assert metric["properties"]["count"]["minimum"] == 1
    assert metric["properties"]["p95_ms"]["minimum"] == 0
    assert schema["properties"]["status"]["enum"] == ["pass", "fail", "incomplete"]
