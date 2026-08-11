from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from picotoopet_core.creative.source import CreativeSourceError, CreativeSourceNormalizer
from picotoopet_core.db.database import Database


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    return database


def _seed_result(
    database: Database,
    *,
    project_key: str,
    quality: str = "PASS",
    work_status: str = "Completed",
    rank: int = 1,
) -> str:
    now = datetime.now(UTC).isoformat()
    work_package_id = str(uuid4())
    result_package_id = str(uuid4())
    source_digest = "a" * 64
    preprocess_digest = "b" * 64
    result_digest = hashlib.sha256(result_package_id.encode("utf-8")).hexdigest()
    evidence_id = f"reviews:key:{result_package_id[:16]}"
    result = {
        "schema_version": "1.0",
        "analysis_profile": "reviews.voice_of_customer.v1",
        "summary": "Drying time matters.",
        "findings": [
            {
                "rank": rank,
                "title": "Drying time",
                "insight": "Customers mention drying time.",
                "confidence": 0.9,
                "evidence_ids": [evidence_id],
            }
        ],
        "warnings": [],
        "needs_deep_ai": False,
        "needs_human": False,
    }
    database.execute(
        "INSERT INTO business_work_packages("
        "work_package_id,idempotency_key,producer_id,producer_version,project_key,analysis_profile,"
        "objective,status,source_digest,compressed_size_bytes,manifest_json,created_at,updated_at,finished_at"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            work_package_id,
            f"source-{work_package_id}",
            "amazon-review-analyzer",
            "1.0.0",
            project_key,
            "reviews.voice_of_customer.v1",
            "Find customer pain points.",
            work_status,
            source_digest,
            100,
            "{}",
            now,
            now,
            now,
        ),
    )
    database.execute(
        "INSERT INTO business_result_packages("
        "result_package_id,work_package_id,analysis_profile,source_digest,preprocess_digest,"
        "model_adapter_version,configured_model_id,template_version,quality_outcome,result_digest,"
        "package_relpath,result_json,warnings_json,created_at"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            result_package_id,
            work_package_id,
            "reviews.voice_of_customer.v1",
            source_digest,
            preprocess_digest,
            "openai-compatible-loopback-v1",
            "gpt-oss:20b",
            "reviews-v1.0.0",
            quality,
            result_digest,
            f"runtime/business/results/{result_package_id}.zip",
            json.dumps(result, ensure_ascii=False, sort_keys=True),
            "[]",
            now,
        ),
    )
    return result_package_id


def test_source_normalizer_derives_stable_finding_ref_and_digest(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        result_id = _seed_result(database, project_key="pet-dryer-us")
        normalized = CreativeSourceNormalizer(database).normalize_source_set([result_id])
        assert normalized.project_key == "pet-dryer-us"
        assert len(normalized.findings) == 1
        finding = normalized.findings[0]
        assert finding.source_finding_ref == f"{result_id}:finding:1"
        assert len(finding.finding_digest) == 64
        assert finding.evidence_ids
    finally:
        database.close()


def test_source_normalizer_rejects_cross_project_results(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        first = _seed_result(database, project_key="project-a")
        second = _seed_result(database, project_key="project-b")
        with pytest.raises(CreativeSourceError, match="SOURCE_PROJECT_MISMATCH"):
            CreativeSourceNormalizer(database).normalize_source_set([first, second])
    finally:
        database.close()


def test_source_normalizer_rejects_non_pass_or_non_completed_source(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        non_pass = _seed_result(database, project_key="project-a", quality="NEEDS_HUMAN")
        with pytest.raises(CreativeSourceError, match="SOURCE_NOT_PASS"):
            CreativeSourceNormalizer(database).normalize_source_set([non_pass])
        non_completed = _seed_result(database, project_key="project-a", work_status="NeedsHuman")
        with pytest.raises(CreativeSourceError, match="SOURCE_WORK_NOT_COMPLETED"):
            CreativeSourceNormalizer(database).normalize_source_set([non_completed])
    finally:
        database.close()


def test_source_normalizer_rejects_invalid_finding_rank(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        result_id = _seed_result(database, project_key="project-a", rank=2)
        with pytest.raises(CreativeSourceError, match="SOURCE_FINDING_RANK_INVALID"):
            CreativeSourceNormalizer(database).normalize_source_set([result_id])
    finally:
        database.close()
