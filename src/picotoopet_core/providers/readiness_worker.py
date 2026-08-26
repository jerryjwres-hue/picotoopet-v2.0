"""Low-frequency Worker-side probes for bounded coding-provider readiness."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from time import monotonic
from typing import Protocol, cast

from picotoopet_core.worker.claude_code_adapter import ClaudeCodeAdapter

from .models import ProviderName, ProviderReadinessStatus
from .readiness import CodexReadinessProbe, ProviderReadinessProjection


class _CodexProbe(Protocol):
    def status(self) -> ProviderReadinessStatus: ...


class _ClaudeProbe(Protocol):
    def probe_readiness(self, *, cwd: Path) -> str: ...


class ProviderReadinessPublisher:
    """Probe configured providers at most once per 30 seconds and publish redacted facts."""

    REFRESH_SECONDS = 30.0
    _TASK_TYPES: dict[ProviderName, str] = {
        "codex": "provider.codex.handoff-v1",
        "claude_code": "provider.claude-code.handoff-v1",
    }

    def __init__(
        self,
        *,
        projection: ProviderReadinessProjection,
        worker_id: str,
        repository: Path,
        codex_executable: Path | None,
        claude_code_executable: Path | None,
        clock: Callable[[], float] = monotonic,
        codex_probe: _CodexProbe | None = None,
        claude_probe: _ClaudeProbe | None = None,
    ) -> None:
        self.projection = projection
        self.worker_id = worker_id
        self.repository = repository
        self.codex_executable = codex_executable
        self.claude_code_executable = claude_code_executable
        self.clock = clock
        self.codex_probe = codex_probe or CodexReadinessProbe(codex_executable)
        self.claude_probe = claude_probe or (
            ClaudeCodeAdapter(claude_code_executable)
            if claude_code_executable is not None
            else None
        )
        self._last_refresh: float | None = None
        self._status: dict[ProviderName, ProviderReadinessStatus] = {}

    def refresh(self, *, force: bool = False) -> dict[ProviderName, ProviderReadinessStatus]:
        """Refresh configured providers only; cached calls perform no CLI work."""

        now = self.clock()
        if (
            not force
            and self._last_refresh is not None
            and now - self._last_refresh < self.REFRESH_SECONDS
        ):
            return dict(self._status)

        if self.codex_executable is not None:
            self._probe_and_publish("codex")
        if self.claude_code_executable is not None:
            self._probe_and_publish("claude_code")
        self._last_refresh = now
        return dict(self._status)

    def status(self, provider: ProviderName) -> ProviderReadinessStatus:
        """Return cached readiness only; never probe as a side effect."""

        return self._status.get(provider, ProviderReadinessStatus.UNAVAILABLE)

    def publish_unavailable(self) -> None:
        """Withdraw configured provider readiness when this Worker stops."""

        for provider in self._configured_providers():
            status = ProviderReadinessStatus.UNAVAILABLE
            self._status[provider] = status
            self.projection.publish(
                worker_id=self.worker_id,
                provider=provider,
                status=status,
                task_type=self._TASK_TYPES[provider],
            )

    def _probe_and_publish(self, provider: ProviderName) -> None:
        try:
            if provider == "codex":
                status = self.codex_probe.status()
            else:
                if self.claude_probe is None:
                    status = ProviderReadinessStatus.UNAVAILABLE
                else:
                    raw = self.claude_probe.probe_readiness(cwd=self.repository)
                    status = ProviderReadinessStatus(raw)
        except (OSError, RuntimeError, ValueError):
            status = ProviderReadinessStatus.UNAVAILABLE
        self._status[provider] = status
        self.projection.publish(
            worker_id=self.worker_id,
            provider=provider,
            status=status,
            task_type=self._TASK_TYPES[provider],
        )

    def _configured_providers(self) -> tuple[ProviderName, ...]:
        providers: list[ProviderName] = []
        if self.codex_executable is not None:
            providers.append(cast(ProviderName, "codex"))
        if self.claude_code_executable is not None:
            providers.append(cast(ProviderName, "claude_code"))
        return tuple(providers)
