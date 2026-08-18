"""Autonomous storage mutations must never escape PicotooPet-managed roots."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from picotoopet_core.autonomous.storage import StorageBoundaryError, StorageLifecycleManager
from picotoopet_core.config.paths import RuntimePaths


NOW = datetime(2026, 8, 18, 3, 0, tzinfo=UTC)


def test_compaction_rejects_source_outside_autonomous_managed_root(tmp_path: Path) -> None:
    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.ensure()
    outside = tmp_path / "user-documents" / "important.txt"
    outside.parent.mkdir()
    outside.write_text("protected user data", encoding="utf-8")
    manager = StorageLifecycleManager(paths, clock=lambda: NOW)

    with pytest.raises(StorageBoundaryError, match="outside autonomous managed root"):
        manager.compact_completed(outside, artifact_key="must-reject")

    assert outside.read_text(encoding="utf-8") == "protected user data"


def test_manager_rejects_protected_root_overlap(tmp_path: Path) -> None:
    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.ensure()

    with pytest.raises(StorageBoundaryError, match="protected root overlaps"):
        StorageLifecycleManager(
            paths,
            protected_roots=(paths.autonomous_staging_dir,),
            clock=lambda: NOW,
        )


def test_cleanup_does_not_follow_symlink_outside_managed_root(tmp_path: Path) -> None:
    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.ensure()
    outside = tmp_path / "outside.tmp"
    outside.write_text("do not delete", encoding="utf-8")
    link = paths.autonomous_disposable_dir / "outside-link.tmp"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation unavailable")

    manager = StorageLifecycleManager(paths, clock=lambda: NOW)
    report = manager.cleanup(grace_period=timedelta(seconds=0))

    assert report.files_deleted == 0
    assert link.exists() or link.is_symlink()
    assert outside.read_text(encoding="utf-8") == "do not delete"


def test_compaction_rejects_directory_and_symlink_sources(tmp_path: Path) -> None:
    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.ensure()
    manager = StorageLifecycleManager(paths, clock=lambda: NOW)

    directory = paths.autonomous_staging_dir / "folder"
    directory.mkdir()
    with pytest.raises(StorageBoundaryError, match="regular file"):
        manager.compact_completed(directory, artifact_key="directory")

    target = paths.autonomous_staging_dir / "target.json"
    target.write_text("data", encoding="utf-8")
    link = paths.autonomous_staging_dir / "link.json"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(StorageBoundaryError, match="symlink"):
        manager.compact_completed(link, artifact_key="symlink")
