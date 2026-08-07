from __future__ import annotations

import json
from pathlib import Path

import pytest

from picotoopet_core.worker.codex_adapter import (
    CodexAdapter,
    CodexAdapterProtocolError,
)


def fixture_path() -> Path:
    return Path(__file__).resolve().parents[2] / "fixtures" / "codex" / "fake_codex_jsonl.py"


def test_fake_codex_runs_with_fixed_argv_and_unknown_usage(tmp_path: Path) -> None:
    executable = fixture_path()
    executable.chmod(0o755)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    adapter = CodexAdapter(executable)

    argv = adapter.build_argv()
    result = adapter.run(prompt="Perform only the approved bounded task.", worktree=worktree)

    assert argv == [
        str(executable),
        "--ask-for-approval",
        "never",
        "--sandbox",
        "workspace-write",
        "-c",
        "plugins=false",
        "exec",
        "--json",
        "--ephemeral",
        "-",
    ]
    assert result.exit_code == 0
    assert result.turns_used == 1
    assert result.event_count == 4
    assert result.provider_usage_unknown is True
    assert [event["type"] for event in result.events] == [
        "thread.started",
        "turn.started",
        "item.completed",
        "turn.completed",
    ]
    assert all("text" not in event for event in result.events)


def test_codex_jsonl_parser_keeps_only_safe_usage_fields() -> None:
    payload = "\n".join(
        [
            json.dumps({"type": "thread.started", "secret": "do-not-project"}),
            json.dumps(
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 10,
                        "cached_input_tokens": 3,
                        "output_tokens": 7,
                        "credits": "not-stable",
                    },
                    "transcript": "must-not-project",
                }
            ),
        ]
    )
    events, turns, unknown = CodexAdapter.parse_jsonl(payload)

    assert turns == 1
    assert unknown is False
    assert events == (
        {"type": "thread.started"},
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 10,
                "cached_input_tokens": 3,
                "output_tokens": 7,
            },
        },
    )


def test_codex_parser_rejects_invalid_json_empty_output_and_turn_overrun() -> None:
    with pytest.raises(CodexAdapterProtocolError, match="JSONL 无效"):
        CodexAdapter.parse_jsonl("not-json")
    with pytest.raises(CodexAdapterProtocolError, match="未返回"):
        CodexAdapter.parse_jsonl("")
    payload = "\n".join(json.dumps({"type": "turn.completed"}) for _ in range(9))
    with pytest.raises(CodexAdapterProtocolError, match="turn"):
        CodexAdapter.parse_jsonl(payload)
