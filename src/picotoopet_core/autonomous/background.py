"""Safe bridge between the existing Mac Worker loop and autonomous scheduling."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from picotoopet_core.automation.capabilities import CapabilityRouter
from picotoopet_core.automation.models import CapabilityRegistration
from picotoopet_core.worker.handlers import WorkerHandler

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
        model_id: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not worker_id.strip():
            raise ValueError("worker_id must not be empty")
        if not model_id.strip():
            raise ValueError("model_id must not be empty")
        self.manager = manager
        self.capability_router = capability_router
        self.runtime = runtime
        self.worker_id = worker_id
        self.local_intelligence_handler = local_intelligence_handler
        self.model_id = model_id
        self._clock = clock or (lambda: datetime.now(UTC))

    def refresh_local_intelligence(self, *, healthy: bool) -> None:
        """Expose exactly one bounded local-model task only while the model is healthy."""

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

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
