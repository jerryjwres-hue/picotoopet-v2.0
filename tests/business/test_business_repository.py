from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from picotoopet_core.business.models import (
    BusinessAnalysisProfile,
    WorkPackageManifest,
)
from picotoopet_core.business.repository import BusinessRepository
from picotoopet_core.db.database import Database


SHA_A = "a" * 64


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    return database


def _manifest(**overrides: object) -> WorkPackageManifest:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "package_id": str(uuid4()),
        "idempotency_key": "reviews-2026-08-10",
        "producer_id": "amazon-review-analyzer",
        "producer_version": "1.0.0",
        "created_at": "2026-08-10T12:00:00Z",
        "project_key": "pet-dryer-us",
        "analysis_profile": "reviews.voice_of_customer.v1",
        "objective": "Identify supported product improvement opportunities.",
        "inputs": [
            {
                "artifact_id": "reviews",
                "path": "inputs/reviews.jsonl",
                "media_type": "application/x-ndjson",
                "sha256": SHA_A,
                "size_bytes": 128,
                "record_key_field": "review_id",
            }
        ],
    }
    payload.update(overrides)
    return WorkPackageManifest.model_validate(payload)


def test_migration_11_creates_business_tables(tmp_path: Path) -> None:
    database = _database(tmp_path)
    tables = {
        row[0]
        for row in database.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    assert {
        "business_work_packages",
        "business_artifacts",
        "business_upload_sessions",
        "business_upload_chunks",
        "local_intelligence_runs",
        "local_intelligence_chunks",
        "business_result_packages",
        "deep_ai_handoffs",
    } <= tables
    assert database.scalar("SELECT MAX(version) FROM schema_migrations") == 11
    database.close()


def test_work_package_manifest_rejects_arbitrary_profile() -> None:
    with pytest.raises(ValidationError):
        _manifest(analysis_profile="free.prompt.v1")


def test_repository_reuses_exact_package_identity(tmp_path: Path) -> None:
    database = _database(tmp_path)
    repository = BusinessRepository(database)
    manifest = _manifest()

    first = repository.create_or_get_work_package(
        manifest,
        source_digest=SHA_A,
        compressed_size_bytes=512,
    )
    second = repository.create_or_get_work_package(
        manifest,
        source_digest=SHA_A,
        compressed_size_bytes=512,
    )

    assert first.work_package_id == second.work_package_id == manifest.package_id
    assert first.analysis_profile is BusinessAnalysisProfile.REVIEWS_VOICE_OF_CUSTOMER_V1
    database.close()


def test_repository_rejects_idempotency_key_reuse_for_different_digest(tmp_path: Path) -> None:
    database = _database(tmp_path)
    repository = BusinessRepository(database)
    first = _manifest()
    repository.create_or_get_work_package(
        first,
        source_digest=SHA_A,
        compressed_size_bytes=512,
    )

    second = _manifest(package_id=str(uuid4()), idempotency_key=first.idempotency_key)
    with pytest.raises(ValueError, match="idempotency"):
        repository.create_or_get_work_package(
            second,
            source_digest="b" * 64,
            compressed_size_bytes=512,
        )
    database.close()
