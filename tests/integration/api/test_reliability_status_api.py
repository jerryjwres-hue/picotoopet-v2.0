"""Superpower v1 reliability status and sanitized black-box API contracts."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.progress.models import ProgressUpdate
from picotoopet_core.progress.repository import ProgressRepository


def _client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    token = "0123456789abcdef0123456789abcdef"
    settings = AppSettings(
        paths=RuntimePaths.from_root(tmp_path / "runtime"),
        api_token=token,
    )
    return TestClient(create_app(settings)), {"Authorization": f"Bearer {token}"}


def test_reliability_status_requires_auth_and_uses_live_lease_plus_progress(
    tmp_path: Path,
) -> None:
    client, headers = _client(tmp_path)
    with client:
        denied = client.get("/api/v1/status/reliability")
        created = client.post(
            "/api/v1/tasks",
            headers=headers,
            json={"task_type": "analysis"},
        ).json()
        services = client.app.state.services
        leased = services.queue.lease_next(
            "worker-reliability",
            supported_task_types=("analysis",),
        )
        assert leased is not None
        ProgressRepository(services.database).append(
            ProgressUpdate(
                task_id=created["task_id"],
                stage="local-analysis",
                completed=3,
                total=10,
                message="正在执行本地分析。",
                component="mac-worker",
            )
        )
        services.worker_state.publish(
            state="online",
            reason="busy",
            worker_id="worker-reliability",
            supported_task_types=("analysis",),
            active_task_id=created["task_id"],
            active_stage="local-analysis",
            observed_at=datetime.now(UTC) - timedelta(minutes=2),
        )

        response = client.get("/api/v1/status/reliability", headers=headers)

    assert denied.status_code == 401
    assert response.status_code == 200
    body = response.json()
    assert body["core_reachable"] is True
    assert body["active_task_id"] == created["task_id"]
    assert body["active_stage"] == "local-analysis"
    assert body["primary_fault"] == "WORKER_STATUS_HEARTBEAT_STALE_WHILE_LEASE_ALIVE"
    assert body["status"] == "failed"
    assert body["memory_pressure"] in {"unknown", "normal", "warn", "high"}


def test_reliability_bundle_is_fixed_sanitized_zip_download(tmp_path: Path) -> None:
    client, headers = _client(tmp_path)
    with client:
        response = client.post("/api/v1/status/reliability/bundle", headers=headers)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "attachment" in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("manifest.json"))

    assert {
        "manifest.json",
        "reliability_snapshot.json",
        "component_health.json",
        "worker_lease.json",
        "progress_events.json",
        "ollama.json",
        "memory.json",
    }.issubset(names)
    assert manifest["schema_version"] == "1.0"
    assert manifest["privacy_policy"] == (
        "structured-facts-only; credentials-redacted; browser-storage-excluded; "
        "no-arbitrary-file-scan"
    )
    assert all("cookie" not in name.lower() for name in names)
    assert all("browser" not in name.lower() for name in names)
