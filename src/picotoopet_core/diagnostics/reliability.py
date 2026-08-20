"""Deterministic Superpower v1 reliability fault classification."""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


MemoryPressureLevel = Literal["unknown", "normal", "warn", "high"]
_MEMORY_FREE_PERCENT = re.compile(r"System-wide memory free percentage:\s*(\d+)%")


class ReliabilityFaultCode(StrEnum):
    """Stable non-secret fault codes shared by diagnostics and the Windows UI."""

    WORKER_STATUS_HEARTBEAT_STALE_WHILE_LEASE_ALIVE = (
        "WORKER_STATUS_HEARTBEAT_STALE_WHILE_LEASE_ALIVE"
    )
    EVENT_STREAM_TRANSIENT     = "EVENT_STREAM_TRANSIENT"
    CORE_UNREACHABLE           = "CORE_UNREACHABLE"
    OLLAMA_SERVER_UNREACHABLE  = "OLLAMA_SERVER_UNREACHABLE"
    MODEL_JOB_TIMEOUT          = "MODEL_JOB_TIMEOUT"
    MODEL_OUTPUT_INVALID       = "MODEL_OUTPUT_INVALID"
    MEMORY_PRESSURE_HIGH       = "MEMORY_PRESSURE_HIGH"


class MemoryPressureSummary(BaseModel):
    """Coarse memory pressure only; never includes process dumps or raw command output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    level: MemoryPressureLevel
    source: str = Field(min_length=1, max_length=80)
    available_bytes: int | None = Field(default=None, ge=0, le=10**16)


class ReliabilityObservation(BaseModel):
    """Bounded facts only; this model never accepts credentials, paths, or raw model text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    observed_at: datetime
    core_reachable: bool
    event_stream_connected: bool | None = None
    worker_status_stale: bool = False
    active_task_lease_alive: bool = False
    ollama_server_reachable: bool | None = None
    model_job_timed_out: bool = False
    model_output_invalid: bool = False
    memory_pressure: MemoryPressureLevel = "unknown"
    active_task_id: str | None = Field(default=None, max_length=200)
    active_stage: str | None = Field(default=None, max_length=100)
    input_chars: int | None = Field(default=None, ge=0, le=1_000_000)

    @model_validator(mode="after")
    def _validate_task_context(self) -> ReliabilityObservation:
        if self.active_stage is not None and self.active_task_id is None:
            raise ValueError("active_stage requires active_task_id")
        return self


class ReliabilitySnapshot(BaseModel):
    """Stable health projection derived only from the supplied observation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    observed_at: datetime
    status: Literal["healthy", "degraded", "failed"]
    primary_fault: ReliabilityFaultCode | None = None
    faults: tuple[ReliabilityFaultCode, ...] = ()
    core_reachable: bool
    event_stream_connected: bool | None = None
    ollama_server_reachable: bool | None = None
    memory_pressure: MemoryPressureLevel
    active_task_id: str | None = Field(default=None, max_length=200)
    active_stage: str | None = Field(default=None, max_length=100)
    input_chars: int | None = Field(default=None, ge=0, le=1_000_000)


_FAULT_PRIORITY: tuple[ReliabilityFaultCode, ...] = (
    ReliabilityFaultCode.CORE_UNREACHABLE,
    ReliabilityFaultCode.WORKER_STATUS_HEARTBEAT_STALE_WHILE_LEASE_ALIVE,
    ReliabilityFaultCode.OLLAMA_SERVER_UNREACHABLE,
    ReliabilityFaultCode.MODEL_JOB_TIMEOUT,
    ReliabilityFaultCode.MODEL_OUTPUT_INVALID,
    ReliabilityFaultCode.MEMORY_PRESSURE_HIGH,
    ReliabilityFaultCode.EVENT_STREAM_TRANSIENT,
)

_FAILED_FAULTS: frozenset[ReliabilityFaultCode] = frozenset(
    {
        ReliabilityFaultCode.CORE_UNREACHABLE,
        ReliabilityFaultCode.WORKER_STATUS_HEARTBEAT_STALE_WHILE_LEASE_ALIVE,
        ReliabilityFaultCode.OLLAMA_SERVER_UNREACHABLE,
        ReliabilityFaultCode.MODEL_JOB_TIMEOUT,
        ReliabilityFaultCode.MODEL_OUTPUT_INVALID,
    }
)


def observe_memory_pressure() -> MemoryPressureSummary:
    """Observe macOS memory pressure with a fixed read-only command and coarse output only."""

    if sys.platform != "darwin":
        return MemoryPressureSummary(level="unknown", source="unsupported-platform")
    try:
        result = subprocess.run(
            ["memory_pressure", "-Q"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except (OSError, subprocess.SubprocessError):
        return MemoryPressureSummary(level="unknown", source="macos-memory-pressure")
    if result.returncode != 0:
        return MemoryPressureSummary(level="unknown", source="macos-memory-pressure")

    match = _MEMORY_FREE_PERCENT.search(result.stdout)
    if match is None:
        return MemoryPressureSummary(level="unknown", source="macos-memory-pressure")
    free_percent = int(match.group(1))
    if free_percent < 8:
        level: MemoryPressureLevel = "high"
    elif free_percent < 15:
        level = "warn"
    else:
        level = "normal"
    return MemoryPressureSummary(level=level, source="macos-memory-pressure")


def classify_reliability(observation: ReliabilityObservation) -> ReliabilitySnapshot:
    """Classify independent component facts without inferring failures from elapsed time."""

    detected: set[ReliabilityFaultCode] = set()

    if not observation.core_reachable:
        detected.add(ReliabilityFaultCode.CORE_UNREACHABLE)
    elif observation.event_stream_connected is False:
        # ── A realtime transport failure is not a Core outage when REST/Core is reachable. ──
        detected.add(ReliabilityFaultCode.EVENT_STREAM_TRANSIENT)

    if observation.worker_status_stale and observation.active_task_lease_alive:
        detected.add(
            ReliabilityFaultCode.WORKER_STATUS_HEARTBEAT_STALE_WHILE_LEASE_ALIVE
        )
    if observation.ollama_server_reachable is False:
        detected.add(ReliabilityFaultCode.OLLAMA_SERVER_UNREACHABLE)
    if observation.model_job_timed_out:
        detected.add(ReliabilityFaultCode.MODEL_JOB_TIMEOUT)
    if observation.model_output_invalid:
        detected.add(ReliabilityFaultCode.MODEL_OUTPUT_INVALID)
    if observation.memory_pressure == "high":
        detected.add(ReliabilityFaultCode.MEMORY_PRESSURE_HIGH)

    faults = tuple(code for code in _FAULT_PRIORITY if code in detected)
    if not faults:
        status: Literal["healthy", "degraded", "failed"] = "healthy"
    elif any(code in _FAILED_FAULTS for code in faults):
        status = "failed"
    else:
        status = "degraded"

    return ReliabilitySnapshot(
        observed_at=observation.observed_at,
        status=status,
        primary_fault=faults[0] if faults else None,
        faults=faults,
        core_reachable=observation.core_reachable,
        event_stream_connected=observation.event_stream_connected,
        ollama_server_reachable=observation.ollama_server_reachable,
        memory_pressure=observation.memory_pressure,
        active_task_id=observation.active_task_id,
        active_stage=observation.active_stage,
        input_chars=observation.input_chars,
    )
