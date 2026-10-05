from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from picotoopet_core.autonomous.connected_evidence import (
    BrowserCaptureIntake,
    ConnectedEvidenceRepository,
    Legacy41Importer,
)
from picotoopet_core.db.database import Database


_DEFAULT_EXTENSION_ID = "miagfkomnofgeeahbficblhlcgahaldp"


def _core(tmp_path: Path) -> tuple[Database, ConnectedEvidenceRepository]:
    database = Database(tmp_path / "runtime" / "database" / "core.db")
    database.open()
    database.apply_migrations()
    return database, ConnectedEvidenceRepository(database)


def _legacy_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE canonical_products (
                product_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                brand TEXT DEFAULT '',
                category TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE consumer_signals (
                signal_id TEXT PRIMARY KEY,
                product_id TEXT NOT NULL,
                source_product_key TEXT,
                source TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                source_signal_id TEXT DEFAULT '',
                rating REAL,
                original_text TEXT NOT NULL,
                signal_date TEXT DEFAULT '',
                source_url TEXT DEFAULT '',
                signal_hash TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                imported_at TEXT NOT NULL
            );
            CREATE TABLE analysis_results (
                analysis_run_id TEXT NOT NULL,
                result_type TEXT NOT NULL,
                result_json TEXT NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT INTO canonical_products VALUES (?, ?, ?, ?, ?, ?)",
            (
                "legacy-product-1",
                "Large Dog Chew Toy",
                "LegacyBrand",
                "dog-toy",
                "2026-08-01T00:00:00+00:00",
                "2026-08-02T00:00:00+00:00",
            ),
        )
        connection.execute(
            "INSERT INTO consumer_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy-signal-1",
                "legacy-product-1",
                None,
                "amazon",
                "review",
                "review-123",
                4.0,
                "Strong toy but the handle is too small for my malamute.",
                "2026-07-20",
                "https://www.amazon.com/dp/B0ABCDEFGHI",
                "legacy-hash-1",
                "{}",
                "2026-08-02T00:00:00+00:00",
            ),
        )
        # Old model output is intentionally present to prove the importer ignores it.
        connection.execute(
            "INSERT INTO analysis_results VALUES (?, ?, ?)",
            ("run-1", "model_prediction", '{"claim":"invented model claim"}'),
        )
        connection.commit()
    finally:
        connection.close()


def test_legacy_41_import_is_read_only_idempotent_and_ignores_model_predictions(
    tmp_path: Path,
) -> None:
    database, repository = _core(tmp_path)
    legacy = tmp_path / "maotai-4.1.db"
    _legacy_database(legacy)
    before = legacy.read_bytes()
    importer = Legacy41Importer(repository)
    try:
        first = importer.import_database(legacy, source_name="maotai-4.1.db")
        second = importer.import_database(legacy, source_name="maotai-4.1.db")

        assert first.import_id == second.import_id
        assert first.status == "completed"
        assert first.products_imported == 1
        assert first.evidence_imported == 1
        assert legacy.read_bytes() == before

        products = repository.list_products(limit=10)
        evidence = repository.list_evidence(product_key=products[0].product_key, limit=20)
        assert products[0].title == "Large Dog Chew Toy"
        assert len(evidence) == 1
        assert evidence[0].text_value.startswith("Strong toy")
        assert evidence[0].external_ref_id == "legacy-signal-1"
        assert "invented model claim" not in " ".join(item.text_value for item in evidence)
        assert repository.count_evidence() == 1
    finally:
        database.close()


def test_browser_capture_intake_persists_only_sanitized_public_evidence_and_replays(
    tmp_path: Path,
) -> None:
    database, repository = _core(tmp_path)
    intake = BrowserCaptureIntake(repository, allowed_extension_id=_DEFAULT_EXTENSION_ID)
    packet: dict[str, object] = {
        "type": "capture_page",
        "extension_id": _DEFAULT_EXTENSION_ID,
        "url": "https://www.amazon.com/dp/B0ABCDEFGHI",
        "page": {
            "product_title": "Large Dog Chew Toy",
            "price": "$29.99",
            "rating": "4.6",
            "review_count": "1,234",
            "visible_signals": [
                {
                    "source_id": "review-1",
                    "text": "Strong toy but the handle is too small for my malamute.",
                    "rating": 4,
                }
            ],
        },
    }
    try:
        first = intake.ingest(packet, idempotency_key="bridge-capture-1")
        replay = intake.ingest(packet, idempotency_key="bridge-capture-1")

        assert first.capture_id == replay.capture_id
        assert first.evidence_count == 2
        assert repository.count_evidence() == 2
        evidence = repository.list_evidence(product_key=first.product_key, limit=20)
        assert {item.evidence_type for item in evidence} == {
            "browser.public_observations",
            "consumer_signal",
        }
        assert all(item.origin == "browser_bridge" for item in evidence)
        assert all("cookie" not in item.provenance for item in evidence)

        changed = dict(packet)
        changed["page"] = {"product_title": "Changed title"}
        with pytest.raises(ValueError, match="idempotency"):
            intake.ingest(changed, idempotency_key="bridge-capture-1")
    finally:
        database.close()


def test_browser_capture_intake_rejects_secret_fields_before_persistence(tmp_path: Path) -> None:
    database, repository = _core(tmp_path)
    intake = BrowserCaptureIntake(repository, allowed_extension_id=_DEFAULT_EXTENSION_ID)
    try:
        with pytest.raises(ValueError, match="secret/session"):
            intake.ingest(
                {
                    "type": "capture_page",
                    "extension_id": _DEFAULT_EXTENSION_ID,
                    "url": "https://www.amazon.com/dp/B0ABCDEFGHI",
                    "page": {"title": "safe", "cookie": "never-store-this"},
                },
                idempotency_key="bridge-secret-1",
            )
        assert repository.count_evidence() == 0
    finally:
        database.close()
