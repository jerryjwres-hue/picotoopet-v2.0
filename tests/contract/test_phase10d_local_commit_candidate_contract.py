from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_phase10d_c_local_commit_candidate_surfaces_exist() -> None:
    required_files = (
        "src/picotoopet_core/providers/commit_models.py",
        "src/picotoopet_core/providers/commit_service.py",
        "src/picotoopet_core/providers/commit_execution.py",
        "src/picotoopet_core/api/routes/provider_commits.py",
    )
    missing = [relative for relative in required_files if not (ROOT / relative).is_file()]
    assert missing == [], f"Phase 10D-C 缺少正式实现文件: {missing}"


def test_phase10d_c_migration_and_worker_are_registered() -> None:
    schema = _read("src/picotoopet_core/db/schema.py")
    cli = _read("src/picotoopet_core/cli.py")

    assert "MIGRATION_008" in schema
    assert "provider_commit_candidates" in schema
    assert "ProviderCommitExecutionCoordinator" in cli
    assert 'TASK_TYPE = "provider.commit.create-v1"' in _read(
        "src/picotoopet_core/providers/commit_execution.py"
    )


def test_phase10d_c_security_boundary_is_frozen_in_source() -> None:
    execution = _read("src/picotoopet_core/providers/commit_execution.py")
    service = _read("src/picotoopet_core/providers/commit_service.py")
    routes = _read("src/picotoopet_core/api/routes/provider_commits.py")

    assert "refs/picotoopet/commit-candidates/" in service
    assert "ProviderCommitService.local_ref" in execution
    assert "hash-object" in execution
    assert "--no-filters" in execution
    assert "commit-tree" in execution
    assert "update-ref" in execution
    assert "require_empty_body" in routes


def test_phase10d_c_windows_surface_is_read_only_and_explicit() -> None:
    panel = _read(
        "windows/desktop/src/PicotooPet.Desktop/Views/Pages/ProviderReviewPanel.xaml"
    )

    assert "本地提交候选" in panel
    assert "commit_ready" in panel
    assert "push" in panel.lower()
    assert "merge-ready" in panel.lower()


def test_phase10d_c_is_retained_in_current_rollup() -> None:
    version = _read("src/picotoopet_core/product-version.txt").strip()
    # Version retention gate     Local commit safety boundary remains in cumulative 24.1.
    assert version == "2.3.24.1"
