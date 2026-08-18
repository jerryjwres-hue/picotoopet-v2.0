"""Useful completed data is compressed; disposable managed data is cleaned safely."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from picotoopet_core.autonomous.storage import StorageLifecycleManager
from picotoopet_core.config.paths import RuntimePaths


NOW = datetime(2026, 8, 18, 3, 0, tzinfo=UTC)


def _manager(tmp_path: Path) -> tuple[RuntimePaths, StorageLifecycleManager]:
    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.ensure()
    return paths, StorageLifecycleManager(paths, clock=lambda: NOW)


def test_runtime_paths_create_separate_autonomous_managed_roots(tmp_path: Path) -> None:
    paths, _manager_instance = _manager(tmp_path)

    assert paths.autonomous_root == paths.runtime_dir / "autonomous"
    assert paths.autonomous_staging_dir.is_dir()
    assert paths.autonomous_disposable_dir.is_dir()
    assert paths.autonomous_archive_dir.is_dir()
    assert paths.autonomous_handoffs_dir.is_dir()
    assert paths.autonomous_state_dir.is_dir()


def test_compact_completed_verifies_archive_before_removing_managed_source(tmp_path: Path) -> None:
    paths, manager = _manager(tmp_path)
    source = paths.autonomous_staging_dir / "research-bundle.json"
    original = ("useful evidence\n" * 500).encode("utf-8")
    source.write_bytes(original)

    report = manager.compact_completed(source, artifact_key="research-bundle-001")

    assert report.files_compacted == 1
    assert report.files_deleted == 1
    assert report.bytes_before == len(original)
    assert report.bytes_after < report.bytes_before
    assert not source.exists()
    assert report.archive_path is not None and report.archive_path.is_file()
    assert report.manifest_path is not None and report.manifest_path.is_file()
    with gzip.open(report.archive_path, "rb") as handle:
        assert handle.read() == original
    manifest = json.loads(report.manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_sha256"] == hashlib.sha256(original).hexdigest()
    assert manifest["archive_sha256"] == hashlib.sha256(report.archive_path.read_bytes()).hexdigest()
    assert manifest["verified"] is True


def test_cleanup_removes_only_expired_disposable_files_and_is_idempotent(tmp_path: Path) -> None:
    paths, manager = _manager(tmp_path)
    expired = paths.autonomous_disposable_dir / "old-crawl.tmp"
    fresh = paths.autonomous_disposable_dir / "fresh-crawl.tmp"
    useful = paths.autonomous_staging_dir / "keep.json"
    expired.write_text("old temporary bytes", encoding="utf-8")
    fresh.write_text("fresh temporary bytes", encoding="utf-8")
    useful.write_text("useful", encoding="utf-8")

    old_timestamp = (NOW - timedelta(hours=48)).timestamp()
    fresh_timestamp = (NOW - timedelta(hours=1)).timestamp()
    os.utime(expired, (old_timestamp, old_timestamp))
    os.utime(fresh, (fresh_timestamp, fresh_timestamp))

    first = manager.cleanup(grace_period=timedelta(hours=24))
    second = manager.cleanup(grace_period=timedelta(hours=24))

    assert first.files_deleted == 1
    assert first.bytes_reclaimed == len("old temporary bytes".encode("utf-8"))
    assert second.files_deleted == 0
    assert not expired.exists()
    assert fresh.exists()
    assert useful.exists()
