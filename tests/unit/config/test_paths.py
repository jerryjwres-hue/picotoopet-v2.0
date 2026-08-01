from pathlib import Path

from picotoopet_core.config.paths import RuntimePaths


def test_runtime_paths_create_only_managed_directories(tmp_path: Path) -> None:
    """运行目录必须完整创建，且所有目录都位于受控根目录内。"""

    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.ensure()

    assert paths.database_dir.is_dir()
    assert paths.results_dir.is_dir()
    assert paths.audit_dir.is_dir()
    assert paths.logs_dir.is_dir()
    assert paths.backups_dir.is_dir()
    assert all(path.is_relative_to(paths.root) for path in paths.managed_directories())
