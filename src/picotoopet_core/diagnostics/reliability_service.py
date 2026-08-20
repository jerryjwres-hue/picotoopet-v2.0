"""Canonical Reliability Diagnostic Black Box aggregation."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime

import httpx

from picotoopet_core.db.database import Database
from picotoopet_core.domain.enums import TaskStatus
from picotoopet_core.ollama.client import (
    OllamaClient,
    OllamaProcessSnapshot,
    OllamaVersionObservation,
)
from picotoopet_core.progress.models import ProgressEvent
from picotoopet_core.progress.repository import ProgressRepository
from picotoopet_core.worker.state import WorkerStateStore

from .reliability import (
    MemoryPressureSummary,
    ReliabilityObservation,
    ReliabilitySnapshot,
    classify_reliability,
    observe_memory_pressure,
)
from .reliability_bundle import (
    ComponentHealthFact,
    ReliabilityBundleBuilder,
    ReliabilityBundleInput,
    WorkerLeaseFact,
)

_MAX_COMPONENT_HEALTH = 64


class ReliabilityService:
    """Aggregate only Core-owned facts and fixed read-only local observations."""

    def __init__(
        self,
        *,
        database: Database,
        worker_state: WorkerStateStore,
        ollama: OllamaClient,
        progress: ProgressRepository,
        bundle_builder: ReliabilityBundleBuilder,
        memory_pressure: Callable[[], MemoryPressureSummary] | None = None,
    ) -> None:
        self.database        = database
        self.worker_state    = worker_state
        self.ollama          = ollama
        self.progress        = progress
        self.bundle_builder  = bundle_builder
        self.memory_pressure = memory_pressure or observe_memory_pressure

    def snapshot(self) -> ReliabilitySnapshot:
        """Return one truthful current projection without creating tasks or loading models."""

        return self._collect().snapshot

    def build_bundle(self):  # type: ignore[no-untyped-def]
        """Build one fixed-entry sanitized ZIP inside the managed diagnostics directory."""

        return self.bundle_builder.build(self._collect())

    def _collect(self) -> ReliabilityBundleInput:
        observed_at = datetime.now(UTC)
        worker       = self.worker_state.read_status(now=observed_at)
        lease        = self._active_lease(observed_at)

        progress_events: tuple[ProgressEvent, ...] = ()
        active_stage: str | None = None
        if lease is not None:
            progress = self.progress.snapshot(lease.task_id, recent_limit=50)
            progress_events = tuple(progress.recent_events)
            active_stage = progress.stage
            if active_stage is None and worker.active_task_id == lease.task_id:
                active_stage = worker.active_stage

        memory = self._memory_pressure()
        ollama_version, ollama_processes, ollama_reachable = self._ollama_facts()
        snapshot = classify_reliability(
            ReliabilityObservation(
                observed_at=observed_at,
                core_reachable=True,
                # ── Transport connectivity is a Windows-client fact; Core must not invent it. ──
                event_stream_connected=None,
                worker_status_stale=worker.reason == "worker_heartbeat_stale",
                active_task_lease_alive=lease is not None,
                ollama_server_reachable=ollama_reachable,
                # ── Model execution faults stay false until a canonical runner records them. ──
                model_job_timed_out=False,
                model_output_invalid=False,
                memory_pressure=memory.level,
                active_task_id=None if lease is None else lease.task_id,
                active_stage=active_stage,
                input_chars=None,
            )
        )
        return ReliabilityBundleInput(
            snapshot=snapshot,
            component_health=self._component_health(),
            worker_lease=lease,
            progress_events=progress_events,
            ollama_version=ollama_version,
            ollama_processes=ollama_processes,
            memory=memory,
        )

    def _active_lease(self, observed_at: datetime) -> WorkerLeaseFact | None:
        row = self.database.fetchone(
            """
            SELECT task_id, lease_owner, lease_expires_at
            FROM tasks
            WHERE status = ?
              AND lease_owner IS NOT NULL
              AND lease_expires_at IS NOT NULL
              AND lease_expires_at >= ?
            ORDER BY lease_expires_at DESC, updated_at DESC
            LIMIT 1
            """,
            (TaskStatus.RUNNING.value, observed_at.isoformat()),
        )
        if row is None:
            return None
        expires_at = _parse_datetime(row["lease_expires_at"])
        if expires_at is None:
            return None
        return WorkerLeaseFact(
            task_id=str(row["task_id"])[:200],
            worker_id=str(row["lease_owner"])[:200],
            lease_alive=True,
            lease_expires_at=expires_at,
        )

    def _component_health(self) -> tuple[ComponentHealthFact, ...]:
        rows = self.database.fetchall(
            """
            SELECT service_name, status, details_json, checked_at
            FROM service_health
            ORDER BY service_name
            LIMIT ?
            """,
            (_MAX_COMPONENT_HEALTH,),
        )
        facts: list[ComponentHealthFact] = []
        for row in rows:
            checked_at = _parse_datetime(row["checked_at"])
            if checked_at is None:
                continue
            facts.append(
                ComponentHealthFact(
                    service_name=str(row["service_name"])[:80],
                    status=str(row["status"])[:40],
                    detail=_safe_health_detail(row["details_json"]),
                    checked_at=checked_at,
                )
            )
        return tuple(facts)

    def _memory_pressure(self) -> MemoryPressureSummary:
        try:
            return self.memory_pressure()
        except Exception:  # noqa: BLE001 - diagnostics must degrade to unknown, never crash Core
            return MemoryPressureSummary(level="unknown", source="observer-failed")

    def _ollama_facts(
        self,
    ) -> tuple[
        OllamaVersionObservation | None,
        OllamaProcessSnapshot | None,
        bool,
    ]:
        version: OllamaVersionObservation | None = None
        processes: OllamaProcessSnapshot | None = None
        reachable = False

        try:
            version = self.ollama.version_info()
            reachable = True
        except (httpx.HTTPError, TypeError, ValueError):
            pass

        try:
            processes = self.ollama.process_snapshot()
            reachable = True
        except (httpx.HTTPError, TypeError, ValueError):
            pass

        return version, processes, reachable


def _safe_health_detail(value: object) -> str:
    """Keep only the Core-owned bounded `detail` field from service-health JSON."""

    if not isinstance(value, str):
        return ""
    try:
        payload = json.loads(value)
    except (TypeError, ValueError):
        return ""
    if not isinstance(payload, dict):
        return ""
    detail = payload.get("detail")
    return detail[:500] if isinstance(detail, str) else ""


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
