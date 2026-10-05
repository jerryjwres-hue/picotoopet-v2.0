"""Reliability bundles are bounded, sanitized, and read only."""

from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from picotoopet_core.diagnostics.reliability import ReliabilityObservation, classify_reliability
from picotoopet_core.diagnostics.reliability_bundle import (
    ComponentHealthFact,
    MemoryPressureSummary,
    ReliabilityBundleBuilder,
    ReliabilityBundleInput,
    WorkerLeaseFact,
)
from picotoopet_core.ollama.client import (
    OllamaLoadedModelObservation,
    OllamaProcessSnapshot,
    OllamaVersionObservation,
)
from picotoopet_core.progress.models import ProgressEvent


def _snapshot():  # type: ignore[no-untyped-def]
    return classify_reliability(
        ReliabilityObservation(
            observed_at=datetime(2026, 8, 20, 5, 20, tzinfo=UTC),
            core_reachable=True,
            event_stream_connected=None,
            worker_status_stale=False,
            active_task_lease_alive=True,
            ollama_server_reachable=True,
            active_task_id="task-123",
            active_stage="local-analysis",
            input_chars=23000,
        )
    )


def _progress_events() -> list[ProgressEvent]:
    started = datetime(2026, 8, 20, 5, 0, tzinfo=UTC)
    return [
        ProgressEvent(
            task_id="task-123",
            sequence=index + 1,
            stage="research-search" if index < 105 else "local-analysis",
            completed=index,
            total=110,
            message=f"safe progress {index}",
            component="mac-worker",
            # ── Bundle must not serialize arbitrary details, even when the ledger has them. ──
            details={"authorization": "Bearer SHOULD_NOT_LEAK"},
            created_at=started + timedelta(seconds=index),
        )
        for index in range(110)
    ]


def _bundle_input() -> ReliabilityBundleInput:
    return ReliabilityBundleInput(
        snapshot=_snapshot(),
        component_health=(
            ComponentHealthFact(
                service_name="database",
                status="ok",
                detail="SQLite healthy; token=SHOULD_NOT_LEAK",
                checked_at=datetime(2026, 8, 20, 5, 19, tzinfo=UTC),
            ),
        ),
        worker_lease=WorkerLeaseFact(
            task_id="task-123",
            worker_id="mac-worker-1",
            lease_alive=True,
            lease_expires_at=datetime(2026, 8, 20, 5, 21, tzinfo=UTC),
        ),
        progress_events=tuple(_progress_events()),
        ollama_version=OllamaVersionObservation(version="0.13.4"),
        ollama_processes=OllamaProcessSnapshot(
            loaded_model_count=1,
            models=(
                OllamaLoadedModelObservation(
                    name="gpt-oss:20b",
                    size_bytes=13_500_000_000,
                    vram_bytes=12_800_000_000,
                ),
            ),
        ),
        memory=MemoryPressureSummary(level="normal", source="macos-memory-pressure"),
    )


def test_bundle_contains_only_fixed_safe_entries_and_last_100_progress_events(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    log = home / ".ollama" / "logs" / "server.log"
    log.parent.mkdir(parents=True)
    log.write_text(
        "\n".join(
            [f"normal line {index}" for index in range(250)]
            + [
                "Authorization: Bearer SERVER_SECRET",
                "Cookie: session=COOKIE_SECRET",
                "api_key=API_KEY_SECRET",
                "normal final line",
            ]
        ),
        encoding="utf-8",
    )
    browser_secret = home / "Library" / "Application Support" / "Browser" / "Cookies"
    browser_secret.parent.mkdir(parents=True)
    browser_secret.write_text("BROWSER_STORAGE_SECRET", encoding="utf-8")

    builder = ReliabilityBundleBuilder(
        managed_output_dir=tmp_path / "runtime" / "diagnostics",
        home_dir=home,
    )
    bundle = builder.build(_bundle_input())

    assert bundle.parent == (tmp_path / "runtime" / "diagnostics").resolve()
    with zipfile.ZipFile(bundle) as archive:
        assert set(archive.namelist()) == {
            "reliability_snapshot.json",
            "component_health.json",
            "worker_lease.json",
            "progress_events.json",
            "ollama.json",
            "memory.json",
            "ollama_server_tail.log",
            "manifest.json",
        }
        progress = json.loads(archive.read("progress_events.json"))
        assert len(progress) == 100
        assert progress[0]["sequence"] == 11
        assert progress[-1]["sequence"] == 110
        assert all("details" not in item for item in progress)

        merged = b"\n".join(archive.read(name) for name in archive.namelist()).decode(
            "utf-8"
        )
        assert "SERVER_SECRET" not in merged
        assert "COOKIE_SECRET" not in merged
        assert "API_KEY_SECRET" not in merged
        assert "SHOULD_NOT_LEAK" not in merged
        assert "BROWSER_STORAGE_SECRET" not in merged
        assert "normal final line" in merged


def test_missing_ollama_log_is_recorded_without_reading_other_files(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "unrelated.txt").write_text("ARBITRARY_FILE_SECRET", encoding="utf-8")

    builder = ReliabilityBundleBuilder(
        managed_output_dir=tmp_path / "runtime" / "diagnostics",
        home_dir=home,
    )
    bundle = builder.build(_bundle_input())

    with zipfile.ZipFile(bundle) as archive:
        assert "ollama_server_tail.log" not in archive.namelist()
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["ollama_log_included"] is False
        merged = b"\n".join(archive.read(name) for name in archive.namelist()).decode(
            "utf-8"
        )
        assert "ARBITRARY_FILE_SECRET" not in merged
