#!/usr/bin/env python3
"""生成 Mac Core REST 延迟分位数报告。"""

from __future__ import annotations

import argparse
import json
import os
import platform
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from picotoopet_core.performance.percentiles import summarize_samples


def parse_args() -> argparse.Namespace:
    """解析基准地址、样本数与输出路径。"""

    parser = argparse.ArgumentParser(description="Picotoo Pet V2 Mac Core 延迟基准")
    parser.add_argument("--base-url", default="http://127.0.0.1:8766")
    parser.add_argument("--samples", type=int, default=500)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def measure(client: httpx.Client, path: str, samples: int) -> dict[str, int | float]:
    """预热后测量指定 REST 路径。"""

    for _ in range(10):
        response = client.get(path)
        response.raise_for_status()

    durations: list[float] = []
    for _ in range(samples):
        started  = time.perf_counter_ns()
        response = client.get(path)
        elapsed  = (time.perf_counter_ns() - started) / 1_000_000
        response.raise_for_status()
        durations.append(elapsed)
    return summarize_samples(durations)


def main() -> int:
    """运行基准并原子写入机器可读报告。"""

    args  = parse_args()
    token = os.environ.get("PICOTOO_API_TOKEN", "")
    if args.samples < 20:
        raise SystemExit("样本数至少为 20。")

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(
        base_url=args.base_url.rstrip("/"),
        headers=headers,
        timeout=httpx.Timeout(5.0),
    ) as client:
        metrics = {"health": measure(client, "/api/v1/health", args.samples)}

    report = {
        "schema_version": "2.2.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "base_url": args.base_url,
            "samples_per_metric": args.samples,
        },
        "metrics": metrics,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(args.output)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
