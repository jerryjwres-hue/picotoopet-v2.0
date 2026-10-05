"""Autonomous services must reuse the existing Mac Core dependency graph."""

from pathlib import Path

from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.services import build_services


def test_build_services_exposes_autonomous_manager_over_existing_workflow_stack(
    tmp_path: Path,
) -> None:
    settings = AppSettings(
        paths=RuntimePaths.from_root(tmp_path / "runtime"),
        api_token="0123456789abcdef0123456789abcdef",
    )
    services = build_services(settings)
    try:
        assert services.autonomous_goals.database is services.database
        assert services.autonomous_manager.database is services.database
        assert services.autonomous_manager.goals is services.autonomous_goals
        assert services.autonomous_manager.workflows is services.workflows
        assert services.reliability.model_runner_status_path == (
            settings.paths.runtime_dir / "model-runner" / "status.json"
        ).resolve()
    finally:
        services.close()
