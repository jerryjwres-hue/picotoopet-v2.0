"""Research Gateway 内部 crawler provider 的固定路由与安全边界。"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from research_gateway.crawler_adapter import (
    CRAWLER_PROVIDER_ALLOWLIST,
    CrawlerAdapter,
    CrawlerDocument,
    CrawlerProvider,
    CrawlerProviderError,
    CrawlLimits,
    CrawlRequest,
    validate_public_http_url,
)


@dataclass
class FakeProvider:
    """记录有限 provider 调用，并返回预设文档或受控失败。"""

    provider: CrawlerProvider
    outcomes: list[CrawlerDocument | CrawlerProviderError]
    calls: list[CrawlRequest] = field(default_factory=list)

    def crawl(self, request: CrawlRequest, limits: CrawlLimits) -> CrawlerDocument:
        self.calls.append(request)
        if not self.outcomes:
            raise AssertionError("provider called more times than configured")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, CrawlerProviderError):
            raise outcome
        return outcome


def _document(
    *,
    provider: CrawlerProvider,
    markdown: str = "# Example\n\nBody",
    title: str = "Example",
    url: str = "https://example.com/article",
) -> CrawlerDocument:
    return CrawlerDocument(
        title=title,
        url=url,
        source="example.com",
        markdown=markdown,
        provider=provider,
        status_code=200,
    )


def _provider(provider: CrawlerProvider, outcome: CrawlerDocument | CrawlerProviderError) -> FakeProvider:
    return FakeProvider(provider, [outcome])


def test_default_limits_are_explicit_and_conservative() -> None:
    limits = CrawlLimits()
    assert limits.max_pages == 3
    assert limits.max_depth == 0
    assert limits.timeout_seconds == 30
    assert limits.max_content_bytes == 262_144
    assert limits.redirect_limit == 5
    assert limits.concurrency == 2
    assert limits.retry_limit == 1


def test_provider_registry_is_a_closed_two_provider_allowlist() -> None:
    assert CRAWLER_PROVIDER_ALLOWLIST == (
        CrawlerProvider.CRAWL4AI,
        CrawlerProvider.SCRAPLING,
    )
    assert {provider.value for provider in CRAWLER_PROVIDER_ALLOWLIST} == {
        "crawl4ai",
        "scrapling",
    }


def test_static_page_prefers_crawl4ai_and_never_runs_scrapling_on_success() -> None:
    crawl4ai = _provider(
        CrawlerProvider.CRAWL4AI,
        _document(provider=CrawlerProvider.CRAWL4AI),
    )
    scrapling = _provider(
        CrawlerProvider.SCRAPLING,
        _document(provider=CrawlerProvider.SCRAPLING),
    )
    adapter = CrawlerAdapter(crawl4ai=crawl4ai, scrapling=scrapling)
    document = adapter.crawl(CrawlRequest(url="https://example.com/article"))
    assert document.provider is CrawlerProvider.CRAWL4AI
    assert document.title == "Example"
    assert len(crawl4ai.calls) == 1
    assert scrapling.calls == []


def test_javascript_page_still_prefers_crawl4ai() -> None:
    crawl4ai = _provider(
        CrawlerProvider.CRAWL4AI,
        _document(provider=CrawlerProvider.CRAWL4AI, markdown="# JS\n\nRendered"),
    )
    scrapling = _provider(
        CrawlerProvider.SCRAPLING,
        _document(provider=CrawlerProvider.SCRAPLING),
    )
    adapter = CrawlerAdapter(crawl4ai=crawl4ai, scrapling=scrapling)
    document = adapter.crawl(CrawlRequest(url="https://example.com/app", javascript=True))
    assert document.provider is CrawlerProvider.CRAWL4AI
    assert crawl4ai.calls[0].javascript is True
    assert scrapling.calls == []


def test_crawl4ai_failure_allows_exactly_one_scrapling_fallback() -> None:
    crawl4ai = _provider(
        CrawlerProvider.CRAWL4AI,
        CrawlerProviderError("crawl_failed", provider=CrawlerProvider.CRAWL4AI),
    )
    scrapling = _provider(
        CrawlerProvider.SCRAPLING,
        _document(provider=CrawlerProvider.SCRAPLING),
    )
    adapter = CrawlerAdapter(crawl4ai=crawl4ai, scrapling=scrapling)
    document = adapter.crawl(CrawlRequest(url="https://example.com/article"))
    assert document.provider is CrawlerProvider.SCRAPLING
    assert len(crawl4ai.calls) == 1
    assert len(scrapling.calls) == 1


def test_both_providers_fail_once_without_recursive_retry() -> None:
    crawl4ai = _provider(
        CrawlerProvider.CRAWL4AI,
        CrawlerProviderError("network_failed", provider=CrawlerProvider.CRAWL4AI),
    )
    scrapling = _provider(
        CrawlerProvider.SCRAPLING,
        CrawlerProviderError("network_failed", provider=CrawlerProvider.SCRAPLING),
    )
    adapter = CrawlerAdapter(crawl4ai=crawl4ai, scrapling=scrapling)
    with pytest.raises(CrawlerProviderError, match="all crawler providers failed"):
        adapter.crawl(CrawlRequest(url="https://example.com/article"))
    assert len(crawl4ai.calls) == 1
    assert len(scrapling.calls) == 1


def test_captcha_failure_never_escalates_to_fallback_or_stealth() -> None:
    crawl4ai = _provider(
        CrawlerProvider.CRAWL4AI,
        CrawlerProviderError(
            "captcha_required",
            provider=CrawlerProvider.CRAWL4AI,
            captcha=True,
        ),
    )
    scrapling = _provider(
        CrawlerProvider.SCRAPLING,
        _document(provider=CrawlerProvider.SCRAPLING),
    )
    adapter = CrawlerAdapter(crawl4ai=crawl4ai, scrapling=scrapling)
    with pytest.raises(CrawlerProviderError, match="captcha_required"):
        adapter.crawl(CrawlRequest(url="https://example.com/challenge"))
    assert len(crawl4ai.calls) == 1
    assert scrapling.calls == []


def test_content_over_limit_is_a_controlled_failure() -> None:
    limits = CrawlLimits(max_content_bytes=32)
    crawl4ai = _provider(
        CrawlerProvider.CRAWL4AI,
        _document(provider=CrawlerProvider.CRAWL4AI, markdown="x" * 33),
    )
    scrapling = _provider(
        CrawlerProvider.SCRAPLING,
        _document(provider=CrawlerProvider.SCRAPLING, markdown="y" * 33),
    )
    adapter = CrawlerAdapter(crawl4ai=crawl4ai, scrapling=scrapling, limits=limits)
    with pytest.raises(CrawlerProviderError, match="content_limit_exceeded"):
        adapter.crawl(CrawlRequest(url="https://example.com/large"))
    assert len(crawl4ai.calls) == 1
    assert len(scrapling.calls) == 1


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "data:text/plain,secret",
        "javascript:alert(1)",
        "http://127.0.0.1/private",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/",
        "https://user:password@example.com/private",
    ],
)
def test_non_public_or_credential_bearing_urls_are_rejected(url: str) -> None:
    with pytest.raises(ValueError, match="public http"):
        validate_public_http_url(url)
