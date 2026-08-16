"""Crawl4AI runner 的有限重试、URL 门禁与浏览器隔离策略。"""

from __future__ import annotations

import argparse
import inspect

import pytest

from research_gateway import crawl4ai_runner


def _args(*, retry_limit: int = 1) -> argparse.Namespace:
    return argparse.Namespace(
        url="https://example.com/",
        javascript=False,
        timeout_seconds=30,
        max_content_bytes=262_144,
        redirect_limit=5,
        retry_limit=retry_limit,
    )


@pytest.mark.asyncio
async def test_transient_network_failure_retries_only_to_explicit_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def fake_crawl_once(_: argparse.Namespace) -> dict[str, object]:
        # 故障注入只验证 retry 状态机，不冒充真实 Crawl4AI 网络 fixture。
        nonlocal calls
        calls += 1
        return {"ok": False, "error": "network_failed", "captcha": False}

    monkeypatch.setattr(crawl4ai_runner, "_crawl_once", fake_crawl_once)
    result = await crawl4ai_runner._run_with_retries(_args(retry_limit=1))

    assert result["error"] == "network_failed"
    assert calls == 2


@pytest.mark.asyncio
async def test_captcha_stops_immediately_without_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def fake_crawl_once(_: argparse.Namespace) -> dict[str, object]:
        # CAPTCHA 只上报，不 fallback、不 retry、更不进入任何 bypass 逻辑。
        nonlocal calls
        calls += 1
        return {"ok": False, "error": "captcha_required", "captcha": True}

    monkeypatch.setattr(crawl4ai_runner, "_crawl_once", fake_crawl_once)
    result = await crawl4ai_runner._run_with_retries(_args(retry_limit=2))

    assert result == {"ok": False, "error": "captcha_required", "captcha": True}
    assert calls == 1


@pytest.mark.asyncio
async def test_timeout_is_bounded_by_retry_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def fake_crawl_once(_: argparse.Namespace) -> dict[str, object]:
        # Timeout 被归一化为受控 timeout，不允许无限循环。
        nonlocal calls
        calls += 1
        raise TimeoutError

    monkeypatch.setattr(crawl4ai_runner, "_crawl_once", fake_crawl_once)
    result = await crawl4ai_runner._run_with_retries(_args(retry_limit=1))

    assert result["error"] == "timeout"
    assert calls == 2


def test_browser_error_classifier_keeps_timeout_distinct_from_network_failure() -> None:
    # 真实 Playwright page timeout 必须保持为 timeout，不能混成普通 network_failed。
    assert (
        crawl4ai_runner._classify_provider_failure(
            "Page.goto: Timeout 1000ms exceeded while navigating"
        )
        == "timeout"
    )
    assert (
        crawl4ai_runner._classify_provider_failure("net::ERR_CONNECTION_RESET")
        == "network_failed"
    )
    assert crawl4ai_runner._classify_provider_failure("unexpected scraper error") == "crawl_failed"


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data",
        "https://user:password@example.com/",
    ],
)
def test_runner_rejects_non_public_or_credential_destinations(url: str) -> None:
    with pytest.raises(ValueError):
        crawl4ai_runner._validate_public_url(url)


def test_runner_source_disables_persistent_profile_downloads_and_stealth() -> None:
    source = inspect.getsource(crawl4ai_runner)

    assert "use_persistent_context=False" in source
    assert "accept_downloads=False" in source
    assert "UndetectedAdapter" not in source
    assert "magic=True" not in source
    assert "storage_state=" not in source
    assert "user_data_dir=" not in source
