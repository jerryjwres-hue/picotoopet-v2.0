from __future__ import annotations

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
