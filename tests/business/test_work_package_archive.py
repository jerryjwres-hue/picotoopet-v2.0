from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest

from picotoopet_core.business.archive import WorkPackageArchiveError, validate_work_package_archive


def _manifest(package_id: str, payload: bytes, *, path: str = "inputs/reviews.jsonl") -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "package_id": package_id,
        "idempotency_key": f"archive-{package_id}",
        "producer_id": "amazon-review-analyzer",
        "producer_version": "1.0.0",
        "created_at": "2026-08-10T12:00:00Z",
        "project_key": "pet-dryer-us",
        "analysis_profile": "reviews.voice_of_customer.v1",
        "objective": "Find supported customer problems.",
        "inputs": [
            {
                "artifact_id": "reviews",
                "path": path,
                "media_type": "application/x-ndjson",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size_bytes": len(payload),
                "record_key_field": "review_id",
            }
        ],
    }


def _valid_archive(tmp_path: Path) -> Path:
    package_id = str(uuid4())
    payload = b'{"review_id":"r1","text":"slow"}\n'
    archive_path = tmp_path / "valid.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            f"{package_id}/work-package.json",
            json.dumps(_manifest(package_id, payload), sort_keys=True),
        )
        archive.writestr(f"{package_id}/inputs/reviews.jsonl", payload)
    return archive_path


def test_valid_archive_returns_exact_digest_and_manifest(tmp_path: Path) -> None:
    archive_path = _valid_archive(tmp_path)
    validated = validate_work_package_archive(archive_path)
    assert validated.manifest.schema_version == "1.0"
    assert validated.source_digest == hashlib.sha256(archive_path.read_bytes()).hexdigest()
    assert validated.uncompressed_size_bytes > 0


@pytest.mark.parametrize("unsafe_name", ["../escape.txt", "/tmp/escape.txt", "root/../../escape.txt"])
def test_archive_rejects_traversal(tmp_path: Path, unsafe_name: str) -> None:
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(unsafe_name, b"x")
    with pytest.raises(WorkPackageArchiveError, match="unsafe_path"):
        validate_work_package_archive(archive_path)


def test_archive_rejects_executable_payload(tmp_path: Path) -> None:
    package_id = str(uuid4())
    payload = b"MZ"
    archive_path = tmp_path / "exe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            f"{package_id}/work-package.json",
            json.dumps(_manifest(package_id, payload, path="inputs/tool.exe"), sort_keys=True),
        )
        archive.writestr(f"{package_id}/inputs/tool.exe", payload)
    with pytest.raises(WorkPackageArchiveError, match="executable"):
        validate_work_package_archive(archive_path)


def test_archive_rejects_duplicate_member_names(tmp_path: Path) -> None:
    package_id = str(uuid4())
    payload = b'{"review_id":"r1"}\n'
    archive_path = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            f"{package_id}/work-package.json",
            json.dumps(_manifest(package_id, payload), sort_keys=True),
        )
        archive.writestr(f"{package_id}/inputs/reviews.jsonl", payload)
        archive.writestr(f"{package_id}/inputs/reviews.jsonl", payload)
    with pytest.warns(UserWarning):
        pass
    with pytest.raises(WorkPackageArchiveError, match="duplicate_path"):
        validate_work_package_archive(archive_path)
