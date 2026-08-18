"""Safe bridge between the existing Mac Worker loop and autonomous scheduling."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from picotoopet_core.automation.capabilities import CapabilityRouter
from picotoopet_core.automation.models import CapabilityRegistration
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.research.execution import ResearchGatewayExecutor
from picotoopet_core.worker.handlers import WorkerHandler

from .discovery import ContentDiscoveryCoordinator
from .human_pipeline import GoalHandoffCoordinator, GoalSynthesisCoordinator
from .local_intelligence import LocalIntelligenceCoordinator
from .storage_worker import StorageMaintenanceCoordinator


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
        storage_maintenance_handler: WorkerHandler | None = None,
        goal_synthesis_handler: WorkerHandler | None = None,
        goal_handoff_handler: WorkerHandler | None = None,
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
        self.goal_synthesis_handler = goal_synthesis_handler
        self.goal_handoff_handler = goal_handoff_handler
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

        # Storage maintenance is allowed to auto-bind only from the canonical
        # PicotooPet runtime layout that owns this same Mac Core database.
        if storage_maintenance_handler is None:
            storage_maintenance_handler = self._storage_handler_from_manager_database()
        self.storage_maintenance_handler = storage_maintenance_handler

    def refresh_local_intelligence(self, *, healthy: bool) -> None:
        """Expose bounded local analysis and derive only capabilities backed by real handlers."""

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

        # Human Goal stages share this Worker. Synthesis follows model health, while the
        # deterministic ZIP handoff remains available during a temporary model outage.
        self.refresh_human_goal_pipeline(local_healthy=healthy)

        # Tool-first gate: local model health is insufficient. A cached fixed
        # Research Gateway readiness probe must also pass before P3 can exist.
        research_healthy = self._refresh_research_health() if healthy else False
        self.refresh_content_discovery(
            local_healthy=healthy,
            research_healthy=research_healthy,
        )

    def refresh_human_goal_pipeline(self, *, local_healthy: bool) -> None:
        """Expose only the two closed human-Goal stages backed by injected fixed handlers."""

        synthesis_healthy = bool(local_healthy and self.goal_synthesis_handler is not None)
        if synthesis_healthy:
            assert self.goal_synthesis_handler is not None
            self.runtime.handlers[GoalSynthesisCoordinator.TASK_TYPE] = self.goal_synthesis_handler
            synthesis_task_types = [GoalSynthesisCoordinator.TASK_TYPE]
        else:
            self.runtime.handlers.pop(GoalSynthesisCoordinator.TASK_TYPE, None)
            synthesis_task_types = []
        self.capability_router.register(
            CapabilityRegistration(
                worker_id=self.worker_id,
                capability=GoalSynthesisCoordinator.CAPABILITY,
                task_types=synthesis_task_types,
                healthy=synthesis_healthy,
                metadata={
                    "runtime": "mac-worker",
                    "transport": "loopback-openai-compatible",
                    "model": self.model_id,
                    "role": "evidence-grounded-goal-synthesis",
                },
                heartbeat_at=self._now(),
            )
        )

        handoff_healthy = self.goal_handoff_handler is not None
        if handoff_healthy:
            assert self.goal_handoff_handler is not None
            self.runtime.handlers[GoalHandoffCoordinator.TASK_TYPE] = self.goal_handoff_handler
            handoff_task_types = [GoalHandoffCoordinator.TASK_TYPE]
        else:
            self.runtime.handlers.pop(GoalHandoffCoordinator.TASK_TYPE, None)
            handoff_task_types = []
        self.capability_router.register(
            CapabilityRegistration(
                worker_id=self.worker_id,
                capability=GoalHandoffCoordinator.CAPABILITY,
                task_types=handoff_task_types,
                healthy=handoff_healthy,
                metadata={
                    "runtime": "mac-worker",
                    "execution": "deterministic-local-packaging",
                    "external_ai_upload_requires_user_action": True,
                },
                heartbeat_at=self._now(),
            )
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

    def refresh_storage_maintenance(self, *, healthy: bool = True) -> None:
        """Expose only the bounded PicotooPet-managed storage maintenance task."""

        enabled = bool(healthy and self.storage_maintenance_handler is not None)
        if enabled:
            assert self.storage_maintenance_handler is not None
            self.runtime.handlers[StorageMaintenanceCoordinator.TASK_TYPE] = (
                self.storage_maintenance_handler
            )
            task_types = [StorageMaintenanceCoordinator.TASK_TYPE]
        else:
            self.runtime.handlers.pop(StorageMaintenanceCoordinator.TASK_TYPE, None)
            task_types = []
        self.capability_router.register(
            CapabilityRegistration(
                worker_id=self.worker_id,
                capability=StorageMaintenanceCoordinator.CAPABILITY,
                task_types=task_types,
                healthy=enabled,
                metadata={
                    "runtime": "mac-worker",
                    "managed_root_only": True,
                    "protected_originals": "excluded",
                    "role": "bounded-storage-maintenance",
                },
                heartbeat_at=self._now(),
            )
        )

    def tick_safely(self) -> AutonomousBackgroundTick:
        """Isolate any autonomous orchestration error from the Worker lifetime."""

        try:
            # Register the real handler before Manager scheduling so P4 never
            # materializes a storage task that this Worker cannot execute.
            if self.storage_maintenance_handler is not None:
                self.refresh_storage_maintenance(healthy=True)
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

    def _storage_handler_from_manager_database(self) -> WorkerHandler | None:
        """Derive a managed runtime only from `<runtime>/database/core.db`."""

        database = getattr(self.manager, "database", None)
        database_path = getattr(database, "path", None)
        if not isinstance(database_path, Path):
            return None
        resolved_database = database_path.expanduser().resolve()
        if resolved_database.name != "core.db" or resolved_database.parent.name != "database":
            return None
        paths = RuntimePaths.from_root(resolved_database.parent.parent)
        if paths.database_file != resolved_database:
            return None
        try:
            return StorageMaintenanceCoordinator(paths).handler
        except OSError:
            return None

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
