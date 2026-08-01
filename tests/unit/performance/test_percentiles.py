"""延迟分位数计算测试。"""

from __future__ import annotations

import pytest

from picotoopet_core.performance.percentiles import summarize_samples


def test_percentiles_use_nearest_rank_and_preserve_maximum() -> None:
    """固定样本必须产生可复算的 p50、p95、p99 和最大值。"""

    summary = summarize_samples([float(value) for value in range(1, 101)])

    assert summary == {
        "count": 100,
        "p50_ms": 50.0,
        "p95_ms": 95.0,
        "p99_ms": 99.0,
        "max_ms": 100.0,
    }


def test_percentiles_reject_empty_sample_set() -> None:
    """没有样本时不得生成具有误导性的性能报告。"""

    with pytest.raises(ValueError, match="至少需要一个样本"):
        summarize_samples([])


def test_percentiles_round_to_three_decimal_places() -> None:
    """报告精度固定为三位小数，避免平台浮点噪声。"""

    summary = summarize_samples([1.23456, 2.34567, 3.45678])

    assert summary["p50_ms"] == 2.346
    assert summary["max_ms"] == 3.457
