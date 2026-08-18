"""Contract tests for safe Maotai OS 4.1 acquisition logic migrated into PicotooPet."""

from __future__ import annotations

from picotoopet_core.autonomous.legacy_acquisition import (
    SourcePolicyMode,
    adaptive_interval_minutes,
    build_discovery_queries,
    classify_source_url,
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


def test_unknown_public_source_defaults_to_yellow_not_silent_green() -> None:
    decision = classify_source_url("https://example.com/public/article")

    assert decision.domain == "example.com"
    assert decision.mode is SourcePolicyMode.YELLOW
    assert decision.browser_session_required is False
    assert decision.autonomous_fetch_allowed is False


def test_explicit_robots_allow_can_promote_ordinary_public_source_to_green() -> None:
    decision = classify_source_url(
        "https://docs.example.com/article",
        robots_allowed=True,
    )

    assert decision.mode is SourcePolicyMode.GREEN
    assert decision.autonomous_fetch_allowed is True
    assert decision.browser_session_required is False


def test_explicit_robots_disallow_blocks_autonomous_fetch() -> None:
    decision = classify_source_url(
        "https://docs.example.com/article",
        robots_allowed=False,
    )

    assert decision.mode is SourcePolicyMode.RED
    assert decision.autonomous_fetch_allowed is False


def test_browser_session_domains_remain_yellow_even_when_public() -> None:
    for url in (
        "https://www.amazon.com/dp/B0ABCDEFGHI",
        "https://www.tiktok.com/@creator/video/123",
        "https://shop.tiktok.com/view/product/123",
    ):
        decision = classify_source_url(url, robots_allowed=True)
        assert decision.mode is SourcePolicyMode.YELLOW
        assert decision.browser_session_required is True
        assert decision.autonomous_fetch_allowed is False


def test_non_public_or_credential_sources_are_red() -> None:
    for url in (
        "file:///tmp/private.txt",
        "http://localhost:8080/page",
        "http://127.0.0.1/page",
        "http://10.0.0.8/page",
        "https://user:password@example.com/page",
    ):
        decision = classify_source_url(url)
        assert decision.mode is SourcePolicyMode.RED
        assert decision.autonomous_fetch_allowed is False
