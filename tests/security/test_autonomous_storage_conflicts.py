"""A reused archive key must never overwrite a different verified archive."""

from __future__ import annotations

import gzip
from datetime import UTC, datetime
from pathlib import Path

import pytest

from picotoopet_core.autonomous.storage import StorageBoundaryError, StorageLifecycleManager
from picotoopet_core.config.paths import RuntimePaths


NOW = datetime(2026, 8, 18, 3, 30, tzinfo=UTC)


def test_different_content_cannot_overwrite_existing_archive_key(tmp_path: Path) -> None:
    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.ensure()
    manager = StorageLifecycleManager(paths, clock=lambda: NOW)

    first = paths.autonomous_staging_dir / "first.json"
    first.write_bytes(b"first verified research bundle" * 20)
    first_report = manager.compact_completed(first, artifact_key="shared-key")
    assert first_report.archive_path is not None
    with gzip.open(first_report.archive_path, "rb") as handle:
        original_archive_content = handle.read()

    second = paths.autonomous_staging_dir / "second.json"
    second.write_bytes(b"different research bundle" * 20)

    with pytest.raises(StorageBoundaryError, match="archive key already exists"):
        manager.compact_completed(second, artifact_key="shared-key")

    assert second.exists()
    with gzip.open(first_report.archive_path, "rb") as handle:
        assert handle.read() == original_archive_content
