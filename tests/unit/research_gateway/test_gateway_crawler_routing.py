"""research.search 上层合同保持不变时的内部 crawler 路由测试。"""

from __future__ import annotations

import json
from dataclasses import dataclass

from research_gateway.crawler_adapter import (
    CrawlLimits,
    CrawlRequest,
    CrawlerDocument,
    CrawlerProvider,
    CrawlerProviderError,
)
from research_gateway.gateway import CommandResult, GatewayDispatcher


@dataclass
class RecordingRunner:
    result: CommandResult

    def __post_init__(self) -> None:
        # 调用记录：搜索发现仍只走既有 mcporter/Exa 固定入口。
        self.calls: list[tuple[list[str], int]] = []

    def __call__(self, argv: list[str], timeout_seconds: int) -> CommandResult:
        self.calls.append((argv, timeout_seconds))
        return self.result


class RecordingCrawler:
    def __init__(self, outcome: CrawlerDocument | CrawlerProviderError) -> None:
        self.limits = CrawlLimits()
        self.outcome = outcome
        self.calls: list[CrawlRequest] = []

    def crawl(self, request: CrawlRequest) -> CrawlerDocument:
        self.calls.append(request)
        if isinstance(self.outcome, CrawlerProviderError):
            raise self.outcome
        return self.outcome


def test_research_search_keeps_public_capability_and_enriches_with_typed_crawl_content() -> None:
    search_payload = json.dumps(
        {
            "results": [
                {
                    "title": "Example search hit",
                    "url": "https://example.com/article",
                }
            ]
        }
    )
    runner = RecordingRunner(CommandResult(returncode=0, stdout=search_payload, stderr=""))
    crawler = RecordingCrawler(
        CrawlerDocument(
            title="Example Article",
            url="https://example.com/article",
            source="example.com",
            markdown="# Example Article\n\nClean body.",
            provider=CrawlerProvider.CRAWL4AI,
            status_code=200,
        )
    )
    gateway = GatewayDispatcher(runner=runner, crawler_adapter=crawler)

    result = gateway.dispatch("research.search", {"query": "example", "limit": 5})
    envelope = json.loads(result.stdout)

    assert result.returncode == 0
    assert envelope["schema_version"] == "1.0"
    assert envelope["query"] == "example"
    assert envelope["documents"] == [
        {
            "markdown": "# Example Article\n\nClean body.",
            "provider": "crawl4ai",
            "source": "example.com",
            "status_code": 200,
            "title": "Example Article",
            "url": "https://example.com/article",
        }
    ]
    assert crawler.calls == [CrawlRequest(url="https://example.com/article")]
    assert runner.calls[0][0][:2] == ["mcporter", "call"]
    assert "exa.web_search_exa" in runner.calls[0][0][2]


def test_research_search_without_installed_adapter_preserves_legacy_raw_output() -> None:
    runner = RecordingRunner(CommandResult(returncode=0, stdout="legacy-search-output", stderr=""))
    gateway = GatewayDispatcher(runner=runner, crawler_adapter=None)

    result = gateway.dispatch("research.search", {"query": "example", "limit": 5})

    assert result.stdout == "legacy-search-output"
    assert result.returncode == 0


def test_research_search_returns_controlled_failure_when_selected_url_cannot_be_crawled() -> None:
    search_payload = json.dumps(
        {"results": [{"url": "https://example.com/article"}]}
    )
    runner = RecordingRunner(CommandResult(returncode=0, stdout=search_payload, stderr=""))
    crawler = RecordingCrawler(
        CrawlerProviderError("all crawler providers failed", provider=CrawlerProvider.SCRAPLING)
    )
    gateway = GatewayDispatcher(runner=runner, crawler_adapter=crawler)

    result = gateway.dispatch("research.search", {"query": "example", "limit": 5})

    assert result.returncode == 69
    assert result.stdout == ""
    assert result.stderr == "crawler providers failed"
    assert len(crawler.calls) == 1
