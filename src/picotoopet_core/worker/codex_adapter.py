"""固定、无交互、低预算的 Codex JSONL 适配器。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Any

from picotoopet_core.providers.process_runner import (
    BoundedProcessCancelled,
    BoundedProcessError,
    BoundedProcessOutputLimit,
    BoundedProcessRunner,
    BoundedProcessTimeout,
)

TASK_TYPE = "provider.codex.handoff-v1"
_MAX_CAPTURE_BYTES = 256 * 1024
_MAX_EVENTS = 100
_MAX_TURNS = 8
_TIMEOUT_SECONDS = 900
_DISABLED_FEATURE = ("plugins", "false")


class CodexAdapterError(RuntimeError):
    """Codex 适配器固定错误。"""


class CodexAdapterTimeout(CodexAdapterError):
    """达到固定墙钟上限。"""


class CodexAdapterCancelled(CodexAdapterError):
    """用户请求取消。"""


class CodexAdapterProtocolError(CodexAdapterError):
    """JSONL 输出不符合有界协议。"""


@dataclass(frozen=True, slots=True)
class CodexRunResult:
    """不包含 prompt、transcript 或原始 stderr 的安全执行摘要。"""

    exit_code: int
    event_count: int
    turns_used: int
    elapsed_seconds: int
    provider_usage_unknown: bool
    events: tuple[dict[str, Any], ...]


class CodexAdapter:
    """只在 Session 独占 worktree 内运行固定 Codex exec 命令。"""

    def __init__(
        self,
        executable: Path | str | None = None,
        *,
        runner: BoundedProcessRunner | None = None,
    ) -> None:
        configured = executable or os.environ.get(
            "PICOTOOPET_CODEX_EXECUTABLE",
            "/opt/homebrew/bin/codex",
        )
        self.executable = Path(configured).expanduser()
        self.runner = runner or BoundedProcessRunner()

    def build_argv(self) -> list[str]:
        """构造固定参数；用户不能添加模型、目录、工具或环境参数。"""

        feature, disabled = _DISABLED_FEATURE
        return [
            str(self.executable),
            "--ask-for-approval",
            "never",
            "--sandbox",
            "workspace-write",
            "-c",
            f"{feature}={disabled}",
            "exec",
            "--json",
            "--ephemeral",
            "-",
        ]

    def run(
        self,
        *,
        prompt: str,
        worktree: Path,
        cancel_event: Event | None = None,
    ) -> CodexRunResult:
        """通过 stdin 传入批准后的派生 prompt，并解析有界 JSONL。"""

        if not prompt.strip():
            raise CodexAdapterProtocolError("Provider prompt 不能为空。")
        cwd = worktree.expanduser().resolve(strict=True)
        if not cwd.is_dir() or cwd.is_symlink():
            raise CodexAdapterProtocolError("Provider worktree 无效。")
        if not self.executable.is_file():
            raise CodexAdapterError("Codex CLI 不可用。")

        try:
            result = self.runner.run(
                argv=self.build_argv(),
                cwd=cwd,
                stdin_text=prompt,
                timeout_seconds=_TIMEOUT_SECONDS,
                output_limit_bytes=_MAX_CAPTURE_BYTES,
                cancel_event=cancel_event,
            )
        except BoundedProcessTimeout as error:
            raise CodexAdapterTimeout("Codex Session 达到 900 秒上限。") from error
        except BoundedProcessCancelled as error:
            raise CodexAdapterCancelled("Codex Session 已取消。") from error
        except BoundedProcessOutputLimit as error:
            raise CodexAdapterProtocolError("Codex 输出超过大小上限。") from error
        except BoundedProcessError as error:
            raise CodexAdapterError("Codex 子进程失败。") from error

        events, turns, usage_unknown = self.parse_jsonl(result.stdout)
        return CodexRunResult(
            exit_code=result.return_code,
            event_count=len(events),
            turns_used=turns,
            elapsed_seconds=result.elapsed_seconds,
            provider_usage_unknown=usage_unknown,
            events=events,
        )

    @staticmethod
    def parse_jsonl(payload: str) -> tuple[tuple[dict[str, Any], ...], int, bool]:
        """只保留固定安全字段；任何未知正文均不进入正式结果。"""

        events: list[dict[str, Any]] = []
        turns = 0
        usage_unknown = True
        for raw_line in payload.splitlines():
            if not raw_line.strip():
                continue
            if len(events) >= _MAX_EVENTS:
                raise CodexAdapterProtocolError("Codex 事件数量超过上限。")
            try:
                raw = json.loads(raw_line)
            except json.JSONDecodeError as error:
                raise CodexAdapterProtocolError("Codex JSONL 无效。") from error
            if not isinstance(raw, dict):
                raise CodexAdapterProtocolError("Codex JSONL 事件必须为对象。")
            event_type = raw.get("type")
            if not isinstance(event_type, str) or not 1 <= len(event_type) <= 80:
                raise CodexAdapterProtocolError("Codex JSONL 事件类型无效。")
            safe: dict[str, Any] = {"type": event_type}
            if event_type == "turn.completed":
                turns += 1
                if turns > _MAX_TURNS:
                    raise CodexAdapterProtocolError("Codex turn 超过固定预算。")
            usage = raw.get("usage")
            if isinstance(usage, dict):
                numeric = {
                    key: int(value)
                    for key, value in usage.items()
                    if key in {"input_tokens", "cached_input_tokens", "output_tokens"}
                    and isinstance(value, int)
                    and 0 <= value <= 10**9
                }
                if numeric:
                    safe["usage"] = numeric
                    usage_unknown = False
            if raw.get("provider_usage_unknown") is True:
                safe["provider_usage_unknown"] = True
            events.append(safe)
        if not events:
            raise CodexAdapterProtocolError("Codex 未返回 JSONL 事件。")
        return tuple(events), turns, usage_unknown
