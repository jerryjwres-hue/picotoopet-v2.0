from __future__ import annotations

import zipfile
from pathlib import Path
from uuid import uuid4

import pytest

from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.creative.store import CreativeArtifactStore


def test_creative_package_write_is_idempotent(tmp_path: Path) -> None:
    store = CreativeArtifactStore(RuntimePaths.from_root(tmp_path / "runtime"))
    package_id = str(uuid4())
    payload = {
        "schema_version": "1.0",
        "creative_package_id": package_id,
        "creative_job_id": str(uuid4()),
        "creative_profile": "creative.content_plan.v1",
        "quality_outcome": "PASS",
    }
    first = store.write_creative_package(package_id, payload)
    second = store.write_creative_package(package_id, payload)
    assert first == second
    assert store.resolve_managed_relative(first[0]).is_file()


def test_creative_package_conflicting_rewrite_fails_closed(tmp_path: Path) -> None:
    store = CreativeArtifactStore(RuntimePaths.from_root(tmp_path / "runtime"))
    package_id = str(uuid4())
    store.write_creative_package(package_id, {"schema_version": "1.0", "value": "a"})
    with pytest.raises(ValueError, match="immutable"):
        store.write_creative_package(package_id, {"schema_version": "1.0", "value": "b"})


def test_handoff_sanitizer_removes_secret_bearing_keys_and_absolute_paths(tmp_path: Path) -> None:
    store = CreativeArtifactStore(RuntimePaths.from_root(tmp_path / "runtime"))
    handoff_id = str(uuid4())
    relative, _ = store.write_handoff_package(
        handoff_id,
        {
            "schema_version": "1.0",
            "authorization": "Bearer should-not-leak",
            "token": "secret",
            "local_path": "/Users/person/private/data.json",
            "bounded_context": "safe evidence",
        },
    )
    with zipfile.ZipFile(store.resolve_managed_relative(relative)) as archive:
        text = archive.read(f"{handoff_id}/creative-deep-ai-handoff.json").decode("utf-8")
    assert "should-not-leak" not in text
    assert '"secret"' not in text
    assert "/Users/person" not in text
    assert "safe evidence" in text
