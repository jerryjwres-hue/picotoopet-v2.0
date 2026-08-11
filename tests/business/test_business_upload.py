from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest

from picotoopet_core.business.models import WorkPackageManifest
from picotoopet_core.business.repository import BusinessRepository
from picotoopet_core.business.store import BusinessArtifactStore
from picotoopet_core.business.upload import BusinessUploadCoordinator, BusinessUploadError
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.db.database import Database


def _manifest(package_id: str, idempotency_key: str) -> WorkPackageManifest:
    return WorkPackageManifest.model_validate(
        {
            "schema_version": "1.0",
            "package_id": package_id,
            "idempotency_key": idempotency_key,
            "producer_id": "inspiration-assistant",
            "producer_version": "1.0.0",
            "created_at": "2026-08-10T12:00:00Z",
            "project_key": "content-lab",
            "analysis_profile": "ideas.pattern_analysis.v1",
            "objective": "Find repeated hooks and supported idea patterns.",
            "inputs": [
                {
                    "artifact_id": "ideas",
                    "path": "inputs/ideas.txt",
                    "media_type": "text/plain",
                    "sha256": "a" * 64,
                    "size_bytes": 12,
                }
            ],
        }
    )


def _coordinator(tmp_path: Path) -> tuple[Database, BusinessUploadCoordinator]:
    paths = RuntimePaths.from_root(tmp_path / "runtime")
    database = Database(paths.database_file)
    database.open()
    database.apply_migrations()
    return database, BusinessUploadCoordinator(
        BusinessRepository(database),
        BusinessArtifactStore(paths),
    )


def test_exact_chunk_retry_is_idempotent(tmp_path: Path) -> None:
    database, coordinator = _coordinator(tmp_path)
    try:
        payload = b"bounded-work-package-bytes"
        digest = hashlib.sha256(payload).hexdigest()
        _package, session = coordinator.prepare(
            _manifest(str(uuid4()), "upload-idempotent"),
            source_digest=digest,
            total_size_bytes=len(payload),
        )
        first = coordinator.write_chunk(
            session.upload_session_id,
            offset=0,
            expected_sha256=digest,
            payload=payload,
        )
        second = coordinator.write_chunk(
            session.upload_session_id,
            offset=0,
            expected_sha256=digest,
            payload=payload,
        )
        assert first.verified_size_bytes == len(payload)
        assert second.verified_size_bytes == len(payload)
    finally:
        database.close()


def test_wrong_offset_fails_closed(tmp_path: Path) -> None:
    database, coordinator = _coordinator(tmp_path)
    try:
        payload = b"0123456789"
        digest = hashlib.sha256(payload).hexdigest()
        _package, session = coordinator.prepare(
            _manifest(str(uuid4()), "upload-offset"),
            source_digest=digest,
            total_size_bytes=len(payload),
        )
        chunk = payload[:-1]
        with pytest.raises(BusinessUploadError, match="CHUNK_OFFSET_INVALID"):
            coordinator.write_chunk(
                session.upload_session_id,
                offset=1,
                expected_sha256=hashlib.sha256(chunk).hexdigest(),
                payload=chunk,
            )
    finally:
        database.close()


def test_same_idempotency_key_different_digest_conflicts(tmp_path: Path) -> None:
    database, coordinator = _coordinator(tmp_path)
    try:
        coordinator.prepare(
            _manifest(str(uuid4()), "same-business-key"),
            source_digest="a" * 64,
            total_size_bytes=100,
        )
        with pytest.raises(ValueError, match="idempotency"):
            coordinator.prepare(
                _manifest(str(uuid4()), "same-business-key"),
                source_digest="b" * 64,
                total_size_bytes=100,
            )
    finally:
        database.close()
