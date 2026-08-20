"""Bounded, sanitized Reliability Diagnostic Black Box bundles."""

from __future__ import annotations

import json
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from picotoopet_core.ollama.client import (
    OllamaProcessSnapshot,
    OllamaVersionObservation,
)
from picotoopet_core.progress.models import ProgressEvent

from .reliability import ReliabilitySnapshot

_MAX_PROGRESS_EVENTS  = 100
_MAX_LOG_LINES        = 200
_MAX_LOG_READ_BYTES   = 128 * 1024
_MAX_LOG_OUTPUT_BYTES = 64 * 1024
_CREDENTIAL_LINE      = re.compile(
    r"(?i)(authorization\s*:|set-cookie\s*:|cookie\s*:|"
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret|token)\s*[=:])"
)
_CREDENTIAL_VALUE     = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret|token)"
    r"\s*([=:])\s*([^\s,;]+)"
)
_BEARER_VALUE         = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+\-/]+=*")


class ComponentHealthFact(BaseModel):
    """A bounded Core-owned component health fact safe for diagnostics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    service_name: str = Field(min_length=1, max_length=80)
    status: str = Field(min_length=1, max_length=40)
    detail: str = Field(default="", max_length=500)
    checked_at: datetime


class WorkerLeaseFact(BaseModel):
    """Only lease/liveness identity facts; no task payload or environment data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str = Field(min_length=1, max_length=200)
    worker_id: str = Field(min_length=1, max_length=200)
    lease_alive: bool
    lease_expires_at: datetime | None = None


class MemoryPressureSummary(BaseModel):
    """Coarse memory pressure only; never includes a process memory dump."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    level: Literal["normal", "warn", "high"]
    source: str = Field(min_length=1, max_length=80)
    available_bytes: int | None = Field(default=None, ge=0, le=10**16)


class ReliabilityBundleInput(BaseModel):
    """Typed inputs allowed into the diagnostic bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot: ReliabilitySnapshot
    component_health: tuple[ComponentHealthFact, ...] = Field(default=(), max_length=64)
    worker_lease: WorkerLeaseFact | None = None
    progress_events: tuple[ProgressEvent, ...] = ()
    ollama_version: OllamaVersionObservation | None = None
    ollama_processes: OllamaProcessSnapshot | None = None
    memory: MemoryPressureSummary


class ReliabilityBundleBuilder:
    """Create one ZIP using only structured facts and one fixed Ollama server log path."""

    def __init__(self, *, managed_output_dir: Path | str, home_dir: Path | str) -> None:
        self.managed_output_dir = Path(managed_output_dir).expanduser().resolve()
        self.home_dir           = Path(home_dir).expanduser().resolve()

    def build(self, data: ReliabilityBundleInput) -> Path:
        """Write a fixed-entry bundle without arbitrary file or browser-storage scans."""

        self.managed_output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = _utc_timestamp(data.snapshot.observed_at)
        bundle    = self.managed_output_dir / f"reliability-{timestamp}.zip"

        entries: dict[str, bytes] = {
            "reliability_snapshot.json": _json_bytes(data.snapshot.model_dump(mode="json")),
            "component_health.json": _json_bytes(
                [
                    {
                        "service_name": item.service_name,
                        "status": item.status,
                        "detail": _sanitize_text(item.detail),
                        "checked_at": item.checked_at.isoformat(),
                    }
                    for item in data.component_health
                ]
            ),
            "worker_lease.json": _json_bytes(
                None if data.worker_lease is None else data.worker_lease.model_dump(mode="json")
            ),
            "progress_events.json": _json_bytes(_safe_progress_events(data.progress_events)),
            "ollama.json": _json_bytes(
                {
                    "version": (
                        None
                        if data.ollama_version is None
                        else data.ollama_version.model_dump(mode="json")
                    ),
                    "processes": (
                        None
                        if data.ollama_processes is None
                        else data.ollama_processes.model_dump(mode="json")
                    ),
                }
            ),
            "memory.json": _json_bytes(data.memory.model_dump(mode="json")),
        }

        log_tail = self._ollama_server_tail()
        if log_tail is not None:
            entries["ollama_server_tail.log"] = log_tail.encode("utf-8")

        manifest = {
            "schema_version": "1.0",
            "generated_at": data.snapshot.observed_at.isoformat(),
            "ollama_log_included": log_tail is not None,
            "progress_event_count": len(_safe_progress_events(data.progress_events)),
            "entries": sorted([*entries, "manifest.json"]),
            "privacy_policy": (
                "structured-facts-only; credentials-redacted; browser-storage-excluded; "
                "no-arbitrary-file-scan"
            ),
        }
        entries["manifest.json"] = _json_bytes(manifest)

        with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(entries):
                archive.writestr(name, entries[name])
        return bundle

    def _ollama_server_tail(self) -> str | None:
        """Read only `~/.ollama/logs/server.log`; no caller-selected input path is accepted."""

        log_path = (self.home_dir / ".ollama" / "logs" / "server.log").resolve()
        expected = self.home_dir / ".ollama" / "logs" / "server.log"
        if log_path != expected.resolve() or not log_path.is_file():
            return None
        try:
            size = log_path.stat().st_size
            with log_path.open("rb") as handle:
                handle.seek(max(0, size - _MAX_LOG_READ_BYTES))
                raw = handle.read(_MAX_LOG_READ_BYTES)
        except OSError:
            return None

        text    = raw.decode("utf-8", errors="replace")
        lines   = text.splitlines()[-_MAX_LOG_LINES:]
        safe    = "\n".join(_sanitize_log_line(line) for line in lines)
        encoded = safe.encode("utf-8")
        if len(encoded) > _MAX_LOG_OUTPUT_BYTES:
            encoded = encoded[-_MAX_LOG_OUTPUT_BYTES:]
            safe    = encoded.decode("utf-8", errors="ignore")
        return safe


def _safe_progress_events(events: tuple[ProgressEvent, ...]) -> list[dict[str, object]]:
    """Drop arbitrary `details` and keep only the newest 100 typed progress facts."""

    bounded = events[-_MAX_PROGRESS_EVENTS:]
    return [
        {
            "task_id": item.task_id,
            "sequence": item.sequence,
            "stage": item.stage,
            "completed": item.completed,
            "total": item.total,
            "message": _sanitize_text(item.message),
            "component": item.component,
            "created_at": item.created_at.isoformat(),
        }
        for item in bounded
    ]


def _sanitize_log_line(line: str) -> str:
    """Conservatively redact any log line that presents credential-like material."""

    bounded = line[:4_000]
    if _CREDENTIAL_LINE.search(bounded):
        return "[REDACTED_CREDENTIAL_LINE]"
    return _sanitize_text(bounded)


def _sanitize_text(value: str) -> str:
    """Redact common bearer/key-value credential forms in bounded structured text."""

    bounded = value[:4_000]
    bounded = _BEARER_VALUE.sub("Bearer [REDACTED]", bounded)
    bounded = _CREDENTIAL_VALUE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]",
        bounded,
    )
    return bounded


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
