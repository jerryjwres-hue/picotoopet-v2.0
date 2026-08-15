from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from research_gateway.gateway import (
    READ_CAPABILITIES,
    CommandResult,
    GatewayDispatcher,
    PolicyError,
)

EXPECTED_READ_CAPABILITIES = {
    "research.search",
    "research.web.read",
    "research.web.crawl",
    "research.web.extract",
    "research.social.search",
    "research.video.search",
    "research.video.transcript",
    "research.github.search",
    "research.community.search",
    "research.company.lookup",
}


@dataclass
class RecordingRunner:
    result: CommandResult

    def __post_init__(self) -> None:
        self.calls: list[tuple[list[str], int]] = []

    def __call__(self, argv: list[str], timeout_seconds: int) -> CommandResult:
        self.calls.append((argv, timeout_seconds))
        return self.result


def test_read_surface_is_frozen() -> None:
    assert READ_CAPABILITIES == EXPECTED_READ_CAPABILITIES


def test_write_shaped_capability_is_rejected_before_execution() -> None:
    runner = RecordingRunner(CommandResult(returncode=0, stdout="unused", stderr=""))
    gateway = GatewayDispatcher(runner=runner)

    with pytest.raises(PolicyError, match="read-only"):
        gateway.dispatch("research.social.post", {"platform": "twitter", "text": "hello"})

    assert runner.calls == []


def test_github_search_uses_structured_argv_and_injected_runner() -> None:
    runner = RecordingRunner(CommandResult(returncode=0, stdout="repo-a\n", stderr=""))
    gateway = GatewayDispatcher(runner=runner)

    result = gateway.dispatch(
        "research.github.search",
        {"query": "AI Agent", "kind": "repos", "limit": 5},
    )

    assert result.stdout == "repo-a\n"
    assert runner.calls == [(["gh", "search", "repos", "AI Agent", "--limit", "5"], 60)]


def test_social_search_never_accepts_arbitrary_command_parameter() -> None:
    runner = RecordingRunner(CommandResult(returncode=0, stdout="unused", stderr=""))
    gateway = GatewayDispatcher(runner=runner)

    with pytest.raises(ValueError, match="unsupported parameter"):
        gateway.dispatch(
            "research.social.search",
            {"platform": "twitter", "query": "OpenAI", "command": "rm -rf ~"},
        )

    assert runner.calls == []


def test_xiaoyuzhou_is_not_a_supported_social_backend() -> None:
    runner = RecordingRunner(CommandResult(returncode=0, stdout="unused", stderr=""))
    gateway = GatewayDispatcher(runner=runner)

    with pytest.raises(ValueError, match="unsupported platform"):
        gateway.dispatch(
            "research.social.search",
            {"platform": "xiaoyuzhou", "query": "AI"},
        )

    assert runner.calls == []


def test_web_crawl_static_routes_to_scrapling_get() -> None:
    runner = RecordingRunner(CommandResult(returncode=0, stdout="page", stderr=""))
    gateway = GatewayDispatcher(runner=runner)

    gateway.dispatch(
        "research.web.crawl",
        {"url": "https://example.com", "mode": "static"},
    )

    assert runner.calls == [
        (
            [
                "mcporter",
                "call",
                "scrapling.get",
                "url=https://example.com",
                "extraction_type=markdown",
                "main_content_only=true",
            ],
            90,
        )
    ]


@pytest.mark.parametrize(
    ("mode", "selector", "timeout"),
    [
        ("dynamic", "scrapling.fetch", 120),
        ("stealth", "scrapling.stealthy_fetch", 150),
    ],
)
def test_web_crawl_browser_modes_are_closed_allowlist(
    mode: str,
    selector: str,
    timeout: int,
) -> None:
    runner = RecordingRunner(CommandResult(returncode=0, stdout="page", stderr=""))
    gateway = GatewayDispatcher(runner=runner)

    gateway.dispatch(
        "research.web.crawl",
        {"url": "https://example.com", "mode": mode},
    )

    assert runner.calls[0][0][:4] == ["mcporter", "call", selector, "url=https://example.com"]
    assert runner.calls[0][1] == timeout


def test_web_crawl_rejects_arbitrary_mcp_selector() -> None:
    runner = RecordingRunner(CommandResult(returncode=0, stdout="unused", stderr=""))
    gateway = GatewayDispatcher(runner=runner)

    with pytest.raises(ValueError, match="unsupported parameter"):
        gateway.dispatch(
            "research.web.crawl",
            {
                "url": "https://example.com",
                "mode": "static",
                "selector": "filesystem.delete_file",
            },
        )

    assert runner.calls == []


def test_web_extract_css_uses_scrapling_before_paid_backend() -> None:
    runner = RecordingRunner(CommandResult(returncode=0, stdout="title", stderr=""))
    gateway = GatewayDispatcher(runner=runner)

    gateway.dispatch(
        "research.web.extract",
        {
            "url": "https://example.com",
            "css_selector": "h1",
            "output": "text",
        },
    )

    assert runner.calls == [
        (
            [
                "mcporter",
                "call",
                "scrapling.get",
                "url=https://example.com",
                "extraction_type=text",
                "main_content_only=true",
                "css_selector=h1",
            ],
            90,
        )
    ]


def test_structured_extract_requires_explicit_paid_backend_approval() -> None:
    runner = RecordingRunner(CommandResult(returncode=0, stdout="unused", stderr=""))
    gateway = GatewayDispatcher(runner=runner)

    with pytest.raises(PolicyError, match="Thunderbit"):
        gateway.dispatch(
            "research.web.extract",
            {
                "url": "https://example.com",
                "schema": {"title": {"type": "string"}},
            },
        )

    assert runner.calls == []


def test_structured_extract_can_use_bounded_thunderbit_tool_after_approval() -> None:
    runner = RecordingRunner(CommandResult(returncode=0, stdout='{"title":"Example"}', stderr=""))
    gateway = GatewayDispatcher(runner=runner)
    schema = {"title": {"type": "string"}}

    gateway.dispatch(
        "research.web.extract",
        {
            "url": "https://example.com",
            "schema": schema,
            "allow_paid_backend": True,
        },
    )

    assert runner.calls == [
        (
            [
                "mcporter",
                "call",
                "thunderbit.thunderbit_extract",
                "url=https://example.com",
                f"schema={json.dumps(schema, separators=(',', ':'), sort_keys=True)}",
            ],
            150,
        )
    ]
