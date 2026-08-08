"""Deterministic typed capability registration and routing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .models import CapabilityRecord, CapabilityRegistration
from .repository import AutomationRepository


class CapabilityRouter:
    """Select healthy fresh local registrations without invoking any provider."""

    def __init__(
        self,
        repository: AutomationRepository,
        *,
        stale_after: timedelta = timedelta(minutes=2),
    ) -> None:
        self.repository = repository
        self.stale_after = stale_after

    def register(self, registration: CapabilityRegistration) -> CapabilityRecord:
        return self.repository.upsert_capability(registration)

    def list(self) -> list[CapabilityRecord]:
        return self.repository.list_capabilities()

    def select(
        self,
        capability: str,
        *,
        task_type: str | None = None,
        now: datetime | None = None,
    ) -> CapabilityRecord | None:
        checked_at = now or datetime.now(UTC)
        candidates = []
        for registration in self.repository.list_capabilities():
            heartbeat = registration.heartbeat_at
            if heartbeat.tzinfo is None:
                heartbeat = heartbeat.replace(tzinfo=UTC)
            if registration.capability != capability or not registration.healthy:
                continue
            if checked_at - heartbeat.astimezone(UTC) > self.stale_after:
                continue
            if task_type is not None and task_type not in registration.task_types:
                continue
            candidates.append(registration)
        return min(candidates, key=lambda item: item.worker_id) if candidates else None
