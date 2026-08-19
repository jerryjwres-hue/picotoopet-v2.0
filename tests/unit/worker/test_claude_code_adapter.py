from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path

import pytest

from picotoopet_core.providers.process_runner import BoundedProcessResult


def _module():  # type: ignore[no-untyped-def]
    name = "picotoopet_core.worker.claude_code_adapter"
    if importlib.util.find_spec(name) is None:
        pytest.fail("bounded Claude Code adapter is not implemented")
    return importlib.import_module(name)


class FakeRunner:
    def __init__(self, *results: BoundedProcessResult) -> None:
        self.results = list(results)
        self.calls: list[dict[str, object]] = []

    def run(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        if not self.results:
            raise AssertionError("unexpected extra provider subprocess call")
        return self.results.pop(0)


def _success_payload() -> str:
    return json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "session_id": "11111111-1111-1111-1111-111111111111",
            "num_turns": 3,
            "is_error": False,
            "stop_reason": "end_turn",
            "total_cost_usd": 0.12,
            "usage": {"input_tokens": 1200, "output_tokens": 400},
            "permission_denials": [],
            "result": "raw answer must not be persisted in safe summary",
        }
    )


def _policy_compatible_help() -> str:
    return " ".join(
        (
            "--safe-mode",
            "--output-format",
            "--max-turns",
            "--no-session-persistence",
            "--permission-mode",
            "--tools",
            "--disallowedTools",
            "--version",
        )
    )


def _result(*, return_code: int, stdout: str) -> BoundedProcessResult:
    return BoundedProcessResult(
        return_code=return_code,
        stdout=stdout,
        stderr="",
        elapsed_seconds=0,
    )


def test_argv_is_fixed_noninteractive_and_file_tools_only(tmp_path: Path) -> None:
    module = _module()
    executable = tmp_path / "claude"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    adapter = module.ClaudeCodeAdapter(executable=executable)

    argv = adapter.build_argv()
    joined = " ".join(argv)

    assert argv[0] == str(executable)
    assert "--safe-mode" in argv
    assert "-p" in argv
    assert "--output-format" in argv and "json" in argv
    assert "--max-turns" in argv and "8" in argv
    assert "--no-session-persistence" in argv
    assert "--permission-mode" in argv and "acceptEdits" in argv
    assert "--tools" in argv and "Read,Edit,Write" in argv
    assert "--disallowedTools" in argv
    assert "Bash" in joined
    assert "WebFetch" in joined
    assert "WebSearch" in joined
    assert "Agent" in joined
    assert "mcp__*" in joined
    assert "--dangerously-skip-permissions" not in argv
    assert "--add-dir" not in argv
    assert "--mcp-config" not in argv
    assert "--permission-prompt-tool" not in argv
    assert "--model" not in argv


def test_run_uses_only_isolated_cwd_fixed_limits_and_safe_summary(tmp_path: Path) -> None:
    module = _module()
    executable = tmp_path / "claude"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    runner = FakeRunner(
        BoundedProcessResult(
            return_code=0,
            stdout=_success_payload(),
            stderr="sensitive stderr is intentionally ignored",
            elapsed_seconds=7,
        )
    )
    adapter = module.ClaudeCodeAdapter(executable=executable, runner=runner)

    result = adapter.run(prompt="make the bounded patch", worktree=worktree)

    assert len(runner.calls) == 1
    call = runner.calls[0]
    assert call["cwd"] == worktree.resolve()
    assert call["stdin_text"] == "make the bounded patch"
    assert call["timeout_seconds"] == 900
    assert call["output_limit_bytes"] == 262144
    assert result.subtype == "success"
    assert result.turns_used == 3
    assert result.elapsed_seconds == 7
    assert result.estimated_cost_usd == pytest.approx(0.12)
    assert result.input_tokens == 1200
    assert result.output_tokens == 400
    assert not hasattr(result, "raw_result")
    assert not hasattr(result, "stderr")
    assert "raw answer" not in repr(result)


def test_result_parser_rejects_non_result_or_over_budget_turns() -> None:
    module = _module()

    with pytest.raises(module.ClaudeCodeAdapterProtocolError):
        module.ClaudeCodeAdapter.parse_result(json.dumps({"type": "assistant"}))
    with pytest.raises(module.ClaudeCodeAdapterProtocolError):
        module.ClaudeCodeAdapter.parse_result(
            json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "session_id": "session",
                    "num_turns": 9,
                    "is_error": False,
                    "usage": {},
                }
            )
        )


def test_readiness_checks_policy_flags_then_auth_without_reading_credentials(tmp_path: Path) -> None:
    module = _module()
    executable = tmp_path / "claude"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    runner = FakeRunner(
        _result(return_code=0, stdout=_policy_compatible_help()),
        _result(return_code=0, stdout=json.dumps({"loggedIn": True})),
    )
    adapter = module.ClaudeCodeAdapter(executable=executable, runner=runner)

    readiness = adapter.probe_readiness(cwd=cwd)

    assert readiness == "ready"
    assert len(runner.calls) == 2
    assert runner.calls[0]["argv"] == [str(executable), "--help"]
    assert runner.calls[1]["argv"] == [str(executable), "auth", "status"]
    assert all(call["stdin_text"] == "" for call in runner.calls)
    assert all(call["timeout_seconds"] <= 15 for call in runner.calls)


def test_readiness_policy_blocks_old_cli_before_authentication(tmp_path: Path) -> None:
    module = _module()
    executable = tmp_path / "claude"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    runner = FakeRunner(_result(return_code=0, stdout="--output-format --max-turns"))
    adapter = module.ClaudeCodeAdapter(executable=executable, runner=runner)

    assert adapter.probe_readiness(cwd=tmp_path) == "policy_blocked"
    assert len(runner.calls) == 1
    assert runner.calls[0]["argv"] == [str(executable), "--help"]


def test_readiness_distinguishes_not_authenticated_and_unavailable(tmp_path: Path) -> None:
    module = _module()
    missing = module.ClaudeCodeAdapter(executable=tmp_path / "missing")
    assert missing.probe_readiness(cwd=tmp_path) == "unavailable"

    executable = tmp_path / "claude"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    runner = FakeRunner(
        _result(return_code=0, stdout=_policy_compatible_help()),
        _result(return_code=1, stdout=json.dumps({"loggedIn": False})),
    )
    adapter = module.ClaudeCodeAdapter(executable=executable, runner=runner)
    assert adapter.probe_readiness(cwd=tmp_path) == "not_authenticated"
