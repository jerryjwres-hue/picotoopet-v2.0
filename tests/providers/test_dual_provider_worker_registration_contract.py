from __future__ import annotations

from pathlib import Path

from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.providers.artifact_store import ProviderReturnArtifactStore
from picotoopet_core.providers.execution import ProviderExecutionCoordinator


def _settings(
    tmp_path: Path,
    *,
    codex: Path | None = None,
    claude: Path | None = None,
) -> AppSettings:
    return AppSettings(
        paths=RuntimePaths.from_root(tmp_path / "runtime"),
        api_token="0123456789abcdef0123456789abcdef",
        provider_repository=tmp_path / "repo",
        provider_worktree_root=tmp_path / "worktrees",
        codex_executable=codex,
        claude_code_executable=claude,
    )


def test_provider_configuration_is_additive_and_fail_closed(tmp_path: Path) -> None:
    codex = tmp_path / "codex"
    claude = tmp_path / "claude"

    codex_only = _settings(tmp_path / "codex-only", codex=codex)
    claude_only = _settings(tmp_path / "claude-only", claude=claude)
    both = _settings(tmp_path / "both", codex=codex, claude=claude)
    neither = _settings(tmp_path / "neither")

    assert codex_only.provider_execution_configured is True
    assert codex_only.configured_coding_providers == ("codex",)
    assert claude_only.provider_execution_configured is True
    assert claude_only.configured_coding_providers == ("claude_code",)
    assert both.configured_coding_providers == ("codex", "claude_code")
    assert neither.provider_execution_configured is False
    assert neither.configured_coding_providers == ()


def test_coordinator_registers_only_explicitly_configured_provider_task_types(tmp_path: Path) -> None:
    coordinator = ProviderExecutionCoordinator(
        queue=None,
        sessions=None,
        repository=tmp_path / "repo",
        worktree_root=tmp_path / "worktrees",
        codex_executable=None,
        claude_code_executable=tmp_path / "claude",
        worker_id="claude-only-worker",
        artifact_store=ProviderReturnArtifactStore(tmp_path / "returns"),
    )

    assert coordinator.configured_task_types == (
        ProviderExecutionCoordinator.CLAUDE_CODE_TASK_TYPE,
    )


def test_loader_and_worker_source_wire_claude_without_auto_install() -> None:
    root = Path(__file__).resolve().parents[2]
    loader = (root / "src/picotoopet_core/config/loader.py").read_text(encoding="utf-8")
    cli = (root / "src/picotoopet_core/cli.py").read_text(encoding="utf-8")

    assert 'PICOTOO_CLAUDE_CODE_EXECUTABLE' in loader
    assert "claude_code_executable=settings.claude_code_executable" in cli
    assert "provider_coordinator.configured_task_types" in cli
    assert "install claude" not in loader.lower()
    assert "npm install" not in loader.lower()
    assert "brew install" not in loader.lower()
