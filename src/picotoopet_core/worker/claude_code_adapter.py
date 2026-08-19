"""Fixed, non-interactive and conservative Claude Code provider adapter."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Literal

from picotoopet_core.providers.process_runner import (
    BoundedProcessCancelled,
    BoundedProcessError,
    BoundedProcessOutputLimit,
    BoundedProcessRunner,
    BoundedProcessTimeout,
)

TASK_TYPE = "provider.claude-code.handoff-v1"
_MAX_CAPTURE_BYTES = 256 * 1024
_MAX_TURNS = 8
_TIMEOUT_SECONDS = 900
_READINESS_TIMEOUT_SECONDS = 10
_READINESS_OUTPUT_BYTES = 128 * 1024
_MAX_PROMPT_CHARS = 128 * 1024
_ALLOWED_TOOLS = "Read,Edit,Write"
_DISALLOWED_TOOLS = (
    "Bash,PowerShell,WebFetch,WebSearch,Agent,NotebookEdit,Skill,ToolSearch,"
    "EnterWorktree,ExitWorktree,TeamCreate,TeamDelete,SendMessage,mcp__*"
)
_REQUIRED_POLICY_FLAGS = frozenset(
    {
        "--safe-mode",
        "--output-format",
        "--max-turns",
        "--no-session-persistence",
        "--permission-mode",
        "--tools",
        "--disallowedTools",
    }
)
_SAFE_SUBTYPES = frozenset(
    {
        "success",
        "error_max_turns",
        "error_max_budget_usd",
        "error_during_execution",
        "error_max_structured_output_retries",
    }
)

ReadinessStatus = Literal["ready", "not_authenticated", "unavailable", "policy_blocked"]


class ClaudeCodeAdapterError(RuntimeError):
    """Claude Code adapter fixed error."""


class ClaudeCodeAdapterTimeout(ClaudeCodeAdapterError):
    """Fixed wall-clock budget was exhausted."""


class ClaudeCodeAdapterCancelled(ClaudeCodeAdapterError):
    """The bounded provider session was cancelled."""


class ClaudeCodeAdapterProtocolError(ClaudeCodeAdapterError):
    """Claude Code output or local execution contract is invalid."""


@dataclass(frozen=True, slots=True)
class ClaudeCodeRunResult:
    """Safe provider summary that deliberately excludes result text and stderr."""

    subtype: str
    turns_used: int
    elapsed_seconds: int
    estimated_cost_usd: float | None
    input_tokens: int | None
    output_tokens: int | None
    provider_usage_unknown: bool


class ClaudeCodeAdapter:
    """Run Claude Code only inside one pre-created isolated provider worktree."""

    def __init__(
        self,
        executable: Path | str | None = None,
        *,
        runner: BoundedProcessRunner | None = None,
    ) -> None:
        configured = executable or os.environ.get(
            "PICOTOOPET_CLAUDE_CODE_EXECUTABLE",
            "/opt/homebrew/bin/claude",
        )
        self.executable = Path(configured).expanduser()
        self.runner = runner or BoundedProcessRunner()

    def build_argv(self) -> list[str]:
        """Build the complete source-controlled argv; callers cannot append provider flags."""

        return [
            str(self.executable),
            "--safe-mode",
            "-p",
            "--output-format",
            "json",
            "--max-turns",
            str(_MAX_TURNS),
            "--no-session-persistence",
            "--permission-mode",
            "acceptEdits",
            "--tools",
            _ALLOWED_TOOLS,
            "--disallowedTools",
            _DISALLOWED_TOOLS,
        ]

    def run(
        self,
        *,
        prompt: str,
        worktree: Path,
        cancel_event: Event | None = None,
    ) -> ClaudeCodeRunResult:
        """Execute one bounded patch lane with prompt only on stdin."""

        safe_prompt = prompt.strip()
        if not safe_prompt or len(safe_prompt) > _MAX_PROMPT_CHARS:
            raise ClaudeCodeAdapterProtocolError("Claude Code Provider prompt invalid.")
        cwd = worktree.expanduser().resolve(strict=True)
        if not cwd.is_dir() or cwd.is_symlink():
            raise ClaudeCodeAdapterProtocolError("Claude Code Provider worktree invalid.")
        if not self.executable.is_file():
            raise ClaudeCodeAdapterError("Claude Code CLI unavailable.")

        try:
            result = self.runner.run(
                argv=self.build_argv(),
                cwd=cwd,
                stdin_text=safe_prompt,
                timeout_seconds=_TIMEOUT_SECONDS,
                output_limit_bytes=_MAX_CAPTURE_BYTES,
                cancel_event=cancel_event,
            )
        except BoundedProcessTimeout as error:
            raise ClaudeCodeAdapterTimeout("Claude Code Session reached the 900 second limit.") from error
        except BoundedProcessCancelled as error:
            raise ClaudeCodeAdapterCancelled("Claude Code Session cancelled.") from error
        except BoundedProcessOutputLimit as error:
            raise ClaudeCodeAdapterProtocolError("Claude Code output exceeded the fixed limit.") from error
        except BoundedProcessError as error:
            raise ClaudeCodeAdapterError("Claude Code subprocess failed.") from error

        parsed = self.parse_result(result.stdout)
        return ClaudeCodeRunResult(
            subtype=parsed.subtype,
            turns_used=parsed.turns_used,
            elapsed_seconds=result.elapsed_seconds,
            estimated_cost_usd=parsed.estimated_cost_usd,
            input_tokens=parsed.input_tokens,
            output_tokens=parsed.output_tokens,
            provider_usage_unknown=parsed.provider_usage_unknown,
        )

    @staticmethod
    def parse_result(payload: str) -> ClaudeCodeRunResult:
        """Parse only safe usage/status fields from Claude JSON; discard answer/transcript fields."""

        try:
            raw = json.loads(payload)
        except json.JSONDecodeError as error:
            raise ClaudeCodeAdapterProtocolError("Claude Code JSON result invalid.") from error
        if not isinstance(raw, dict) or raw.get("type") != "result":
            raise ClaudeCodeAdapterProtocolError("Claude Code must return exactly one result object.")

        subtype = raw.get("subtype")
        if not isinstance(subtype, str) or subtype not in _SAFE_SUBTYPES:
            raise ClaudeCodeAdapterProtocolError("Claude Code result subtype invalid.")
        turns = raw.get("num_turns")
        if not isinstance(turns, int) or isinstance(turns, bool) or not 0 <= turns <= _MAX_TURNS:
            raise ClaudeCodeAdapterProtocolError("Claude Code turn count exceeds fixed budget.")

        estimated_cost = raw.get("total_cost_usd")
        safe_cost: float | None = None
        if isinstance(estimated_cost, (int, float)) and not isinstance(estimated_cost, bool):
            candidate = float(estimated_cost)
            if math.isfinite(candidate) and 0.0 <= candidate <= 1_000_000.0:
                safe_cost = candidate

        usage = raw.get("usage")
        input_tokens: int | None = None
        output_tokens: int | None = None
        if isinstance(usage, dict):
            input_tokens = ClaudeCodeAdapter._safe_token_count(usage.get("input_tokens"))
            output_tokens = ClaudeCodeAdapter._safe_token_count(usage.get("output_tokens"))

        provider_usage_unknown = safe_cost is None and input_tokens is None and output_tokens is None
        return ClaudeCodeRunResult(
            subtype=subtype,
            turns_used=turns,
            elapsed_seconds=0,
            estimated_cost_usd=safe_cost,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            provider_usage_unknown=provider_usage_unknown,
        )

    def probe_readiness(self, *, cwd: Path) -> ReadinessStatus:
        """Verify policy-compatible CLI flags before asking the CLI for non-secret auth status."""

        if not self.executable.is_file():
            return "unavailable"
        try:
            working_directory = cwd.expanduser().resolve(strict=True)
        except (FileNotFoundError, OSError):
            return "policy_blocked"
        if not working_directory.is_dir() or working_directory.is_symlink():
            return "policy_blocked"

        try:
            help_result = self.runner.run(
                argv=[str(self.executable), "--help"],
                cwd=working_directory,
                stdin_text="",
                timeout_seconds=_READINESS_TIMEOUT_SECONDS,
                output_limit_bytes=_READINESS_OUTPUT_BYTES,
            )
        except BoundedProcessError:
            return "policy_blocked"
        if help_result.return_code != 0:
            return "policy_blocked"
        if any(flag not in help_result.stdout for flag in _REQUIRED_POLICY_FLAGS):
            return "policy_blocked"

        try:
            auth_result = self.runner.run(
                argv=[str(self.executable), "auth", "status"],
                cwd=working_directory,
                stdin_text="",
                timeout_seconds=_READINESS_TIMEOUT_SECONDS,
                output_limit_bytes=_READINESS_OUTPUT_BYTES,
            )
        except BoundedProcessError:
            return "policy_blocked"

        if auth_result.return_code == 0:
            try:
                auth_payload = json.loads(auth_result.stdout)
            except json.JSONDecodeError:
                # Claude documents exit status as authoritative; avoid depending on credential details.
                return "ready"
            if isinstance(auth_payload, dict) and auth_payload.get("loggedIn") is False:
                return "not_authenticated"
            return "ready"
        if auth_result.return_code == 1:
            return "not_authenticated"
        return "policy_blocked"

    @staticmethod
    def _safe_token_count(value: object) -> int | None:
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 10**9:
            return value
        return None
