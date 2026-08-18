"""Contract tests for safe Maotai OS 4.1 acquisition logic migrated into PicotooPet."""

from __future__ import annotations

from picotoopet_core.autonomous.legacy_acquisition import (
    adaptive_interval_minutes,
    build_discovery_queries,
    information_gain_score,
)


def test_adaptive_interval_uses_legacy_backoff_without_unbounded_growth() -> None:
    assert adaptive_interval_minutes(base_minutes=30, change_rate=0.8, failure_count=0) == 60
    assert adaptive_interval_minutes(base_minutes=120, change_rate=0.8, failure_count=0) == 60
    assert adaptive_interval_minutes(base_minutes=120, change_rate=0.01, failure_count=0) == 240
    assert adaptive_interval_minutes(base_minutes=30, change_rate=0.2, failure_count=2) == 120
    assert adaptive_interval_minutes(base_minutes=30, change_rate=0.2, failure_count=99) == 1920


def test_information_gain_score_matches_legacy_monotonic_formula() -> None:
    empty = information_gain_score(products=0, signals=0, opportunities=0)
    small = information_gain_score(products=1, signals=3, opportunities=0)
    richer = information_gain_score(products=2, signals=12, opportunities=1)

    assert empty == 0.0
    assert small > empty
    assert richer > small
    assert information_gain_score(products=-10, signals=-10, opportunities=-10) == 0.0


def test_discovery_queries_are_objective_specific_deterministic_and_bounded() -> None:
    objective = "研究大型犬耐咬玩具，找消费者痛点和 TikTok 内容方向"

    first = build_discovery_queries(objective)
    second = build_discovery_queries(objective)

    assert first == second
    assert len(first) == 4
    assert len(set(first)) == 4
    assert all(objective in query for query in first)
    assert all(1 <= len(query) <= 240 for query in first)
    assert any("consumer pain points" in query for query in first)
    assert any("creator content trends" in query for query in first)
    assert any("comparison purchase intent" in query for query in first)
    assert any("recent discussions" in query for query in first)


def test_discovery_queries_trim_and_bound_long_objectives_without_blank_queries() -> None:
    queries = build_discovery_queries("  " + ("大型犬用品 " * 100) + "  ", max_queries=3)

    assert len(queries) == 3
    assert len(set(queries)) == 3
    assert all(query == query.strip() for query in queries)
    assert all(1 <= len(query) <= 240 for query in queries)


def test_discovery_query_count_is_clamped_to_small_safe_range() -> None:
    assert len(build_discovery_queries("宠物内容趋势", max_queries=1)) == 1
    assert len(build_discovery_queries("宠物内容趋势", max_queries=99)) == 4
