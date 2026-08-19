"""Bounded provider CLI probes and redacted Worker-to-Core readiness projection."""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from picotoopet_core.automation.capabilities import CapabilityRouter
from picotoopet_core.automation.models import CapabilityRecord, CapabilityRegistration

from .models import ProviderName, ProviderReadinessStatus


class CodexReadinessProbe:
    """Run fixed `codex login status` without returning or persisting raw output."""

    def __init__(self, executable: Path | None) -> None:
        self.executable = executable

    def status(self) -> ProviderReadinessStatus:
        if self.executable is None:
            return ProviderReadinessStatus.UNAVAILABLE
        executable = self.executable.expanduser()
        if not executable.is_file() or not os.access(executable, os.X_OK):
            return ProviderReadinessStatus.UNAVAILABLE
        try:
            result = subprocess.run(
                [str(executable), "login", "status"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=self._safe_environment(),
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ProviderReadinessStatus.UNAVAILABLE
        if result.returncode == 0:
            return ProviderReadinessStatus.READY
        return ProviderReadinessStatus.NOT_AUTHENTICATED

    @staticmethod
    def _safe_environment() -> dict[str, str]:
        allowed = ("HOME", "PATH", "TMPDIR", "LANG", "LC_ALL")
        return {
            key: value
            for key in allowed
            if (value := os.environ.get(key)) is not None
        }


class ProviderReadinessProjection:
    """Publish/read only short-lived non-secret readiness facts through capability heartbeats."""

    _CAPABILITIES: dict[ProviderName, str] = {
        "codex": "coding.provider.codex",
        "claude_code": "coding.provider.claude_code",
    }

    def __init__(self, router: CapabilityRouter) -> None:
        self.router = router

    @classmethod
    def capability_for(cls, provider: ProviderName) -> str:
        return cls._CAPABILITIES[provider]

    def publish(
        self,
        *,
        worker_id: str,
        provider: ProviderName,
        status: ProviderReadinessStatus,
        task_type: str,
        heartbeat_at: datetime | None = None,
    ) -> CapabilityRecord:
        """Persist only provider name, readiness enum and runtime identity."""

        return self.router.register(
            CapabilityRegistration(
                worker_id=worker_id,
                capability=self.capability_for(provider),
                task_types=[task_type] if status is ProviderReadinessStatus.READY else [],
                healthy=status is ProviderReadinessStatus.READY,
                metadata={
                    "runtime": "mac-worker",
                    "provider": provider,
                    "readiness": status.value,
                },
                heartbeat_at=heartbeat_at or datetime.now(UTC),
            )
        )

    def status(
        self,
        provider: ProviderName,
        *,
        now: datetime | None = None,
    ) -> ProviderReadinessStatus:
        """Read the freshest non-stale readiness fact; missing/stale/malformed is unavailable."""

        checked_at = self._as_utc(now or datetime.now(UTC))
        capability = self.capability_for(provider)
        candidates: list[CapabilityRecord] = []
        for record in self.router.list():
            heartbeat = self._as_utc(record.heartbeat_at)
            if record.capability != capability:
                continue
            if checked_at - heartbeat > self.router.stale_after:
                continue
            if record.metadata.get("runtime") != "mac-worker":
                continue
            if record.metadata.get("provider") != provider:
                continue
            candidates.append(record)
        if not candidates:
            return ProviderReadinessStatus.UNAVAILABLE
        freshest = max(
            candidates,
            key=lambda item: (self._as_utc(item.heartbeat_at), item.worker_id),
        )
        value = freshest.metadata.get("readiness")
        if not isinstance(value, str):
            return ProviderReadinessStatus.UNAVAILABLE
        try:
            return ProviderReadinessStatus(value)
        except ValueError:
            return ProviderReadinessStatus.UNAVAILABLE

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
