"""Safe bridge between the existing Mac Worker loop and autonomous scheduling."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from picotoopet_core.automation.capabilities import CapabilityRouter
from picotoopet_core.automation.models import CapabilityRegistration
from picotoopet_core.research.execution import ResearchGatewayExecutor
from picotoopet_core.worker.handlers import WorkerHandler

from .discovery import ContentDiscoveryCoordinator
from .local_intelligence import LocalIntelligenceCoordinator


class _AutonomousManager(Protocol):
    def tick(self) -> Any:
        """Return one small autonomous scheduling decision."""


class _WorkerRuntime(Protocol):
    handlers: dict[str, WorkerHandler]


class AutonomousBackgroundTick(BaseModel):
    """Sanitized status safe to log or expose in later monitoring UI."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    succeeded: bool
    action: str
    goal_id: str | None = None
    workflow_id: str | None = None
    error_code: str | None = None


class AutonomousBackgroundCoordinator:
    """Share one existing Worker process; never create another scheduler or daemon."""

    def __init__(
        self,
        *,
        manager: _AutonomousManager,
        capability_router: CapabilityRouter,
        runtime: _WorkerRuntime,
        worker_id: str,
        local_intelligence_handler: WorkerHandler,
        content_discovery_handler: WorkerHandler | None = None,
        research_probe: Callable[[], bool] | None = None,
        model_id: str,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        research_probe_interval_seconds: float = 15.0,
    ) -> None:
        if not worker_id.strip():
            raise ValueError("worker_id must not be empty")
        if not model_id.strip():
            raise ValueError("model_id must not be empty")
        if research_probe_interval_seconds <= 0:
            raise ValueError("research_probe_interval_seconds must be positive")
        self.manager = manager
        self.capability_router = capability_router
        self.runtime = runtime
        self.worker_id = worker_id
        self.local_intelligence_handler = local_intelligence_handler
        self.model_id = model_id
        self._clock = clock or (lambda: datetime.now(UTC))
        self._monotonic = monotonic or time.monotonic
        self._research_probe_interval_seconds = research_probe_interval_seconds
        self._research_last_probe = float("-inf")
        self._research_healthy_cached = False

        # Reuse the exact local adapter already injected by the existing Worker CLI.
        # This avoids creating a second gpt-oss agent/model client solely for discovery.
        handler_owner = getattr(local_intelligence_handler, "__self__", None)
        if content_discovery_handler is None and isinstance(
            handler_owner, LocalIntelligenceCoordinator
        ):
            search_executor = ResearchGatewayExecutor()
            content_discovery_handler = ContentDiscoveryCoordinator(
                search=search_executor,
                local=handler_owner.adapter,
            ).handler
            if research_probe is None:
                research_probe = search_executor.search_ready
        self.content_discovery_handler = content_discovery_handler
        self._research_probe = research_probe

    def refresh_local_intelligence(self, *, healthy: bool) -> None:
        """Expose bounded local analysis and derive discovery only when tools are healthy too."""

        if healthy:
            self.runtime.handlers[LocalIntelligenceCoordinator.TASK_TYPE] = (
                self.local_intelligence_handler
            )
            task_types = [LocalIntelligenceCoordinator.TASK_TYPE]
        else:
            self.runtime.handlers.pop(LocalIntelligenceCoordinator.TASK_TYPE, None)
            task_types = []
        self.capability_router.register(
            CapabilityRegistration(
                worker_id=self.worker_id,
                capability=LocalIntelligenceCoordinator.CAPABILITY,
                task_types=task_types,
                healthy=healthy,
                metadata={
                    "runtime": "mac-worker",
                    "transport": "loopback-openai-compatible",
                    "model": self.model_id,
                    "role": "bounded-local-analysis",
                },
                heartbeat_at=self._now(),
            )
        )
        # Tool-first gate: local model health is insufficient. A cached fixed
        # Research Gateway readiness probe must also pass before P3 can exist.
        research_healthy = self._refresh_research_health() if healthy else False
        self.refresh_content_discovery(
            local_healthy=healthy,
            research_healthy=research_healthy,
        )

    def refresh_content_discovery(self, *, local_healthy: bool, research_healthy: bool) -> None:
        """Expose P3 discovery only when both evidence tools and local screening are healthy."""

        healthy = bool(
            local_healthy
            and research_healthy
            and self.content_discovery_handler is not None
        )
        if healthy:
            assert self.content_discovery_handler is not None
            self.runtime.handlers[ContentDiscoveryCoordinator.TASK_TYPE] = (
                self.content_discovery_handler
            )
            task_types = [ContentDiscoveryCoordinator.TASK_TYPE]
        else:
            self.runtime.handlers.pop(ContentDiscoveryCoordinator.TASK_TYPE, None)
            task_types = []
        self.capability_router.register(
            CapabilityRegistration(
                worker_id=self.worker_id,
                capability=ContentDiscoveryCoordinator.CAPABILITY,
                task_types=task_types,
                healthy=healthy,
                metadata={
                    "runtime": "mac-worker",
                    "pipeline": "research-gateway-then-local-scout",
                    "model": self.model_id,
                    "read_only": True,
                },
                heartbeat_at=self._now(),
            )
        )

    def tick_safely(self) -> AutonomousBackgroundTick:
        """Isolate any autonomous orchestration error from the Worker lifetime."""

        try:
            result = self.manager.tick()
        except Exception:
            return AutonomousBackgroundTick(
                succeeded=False,
                action="autonomous_tick_failed",
                error_code="AUTONOMOUS_TICK_FAILED",
            )
        return AutonomousBackgroundTick(
            succeeded=True,
            action=str(getattr(result, "action", "autonomous_tick_completed")),
            goal_id=(
                getattr(result, "created_goal_id", None)
                or getattr(result, "active_goal_id", None)
            ),
            workflow_id=getattr(result, "workflow_id", None),
        )

    def _refresh_research_health(self) -> bool:
        if self._research_probe is None or self.content_discovery_handler is None:
            return False
        now = self._monotonic()
        if now - self._research_last_probe < self._research_probe_interval_seconds:
            return self._research_healthy_cached
        self._research_last_probe = now
        try:
            self._research_healthy_cached = bool(self._research_probe())
        except Exception:
            self._research_healthy_cached = False
        return self._research_healthy_cached

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
