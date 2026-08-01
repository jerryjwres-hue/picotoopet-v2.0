"""无第三方依赖的确定性延迟分位数计算。"""

from __future__ import annotations

import math
from collections.abc import Iterable


def _nearest_rank(sorted_samples: list[float], percentile: float) -> float:
    """按最近秩定义读取分位数，结果可跨语言复算。"""

    rank  = max(1, math.ceil(percentile * len(sorted_samples)))
    value = sorted_samples[rank - 1]
    return round(value, 3)


def summarize_samples(samples: Iterable[float]) -> dict[str, int | float]:
    """输出 count、p50、p95、p99 与最大值。"""

    ordered = sorted(float(sample) for sample in samples)
    if not ordered:
        raise ValueError("至少需要一个样本才能生成性能报告。")
    if ordered[0] < 0:
        raise ValueError("延迟样本不得为负数。")

    return {
        "count": len(ordered),
        "p50_ms": _nearest_rank(ordered, 0.50),
        "p95_ms": _nearest_rank(ordered, 0.95),
        "p99_ms": _nearest_rank(ordered, 0.99),
        "max_ms": round(ordered[-1], 3),
    }
