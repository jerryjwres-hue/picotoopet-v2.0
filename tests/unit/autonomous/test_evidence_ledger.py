from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from picotoopet_core.autonomous.evidence_ledger import (
    CanonicalEvidenceCreate,
    CanonicalEvidenceLedger,
    EvidenceOrigin,
    EvidenceTrust,
)
from picotoopet_core.autonomous.legacy_import import Maotai41Importer
from picotoopet_core.db.database import Database


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "runtime" / "database" / "core.db")
    database.open()
    database.apply_migrations()
    return database


def test_canonical_evidence_is_replay_safe_traceable_and_goal_scoped(tmp_path: Path) -> None:
    database = _database(tmp_path)
    ledger = CanonicalEvidenceLedger(database)
    captured_at = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    request = CanonicalEvidenceCreate(
        goal_id=None,
        subject_key="asin:B076F7HM8T",
        evidence_type="consumer_signal",
        source="amazon",
        platform="amazon",
        source_url="https://www.amazon.com/dp/B076F7HM8T",
        source_entity_id="R-001",
        text_value="Large dog destroyed it after repeated chewing.",
        numeric_value=2.0,
        value={"rating": 2.0, "verified": True},
        trust_level=EvidenceTrust.B,
        confidence=0.95,
        captured_at=captured_at,
        source_updated_at=None,
        provenance={"collector": "maotai-4.1-compat"},
        origin_kind=EvidenceOrigin.LEGACY_4_1,
        origin_ref="consumer_signals:R-001",
    )

    first = ledger.ingest(request)
    replay = ledger.ingest(request)
    assert replay.evidence_id == first.evidence_id
    assert first.raw_hash == hashlib.sha256(
        b'Large dog destroyed it after repeated chewing.'
    ).hexdigest()
    assert first.origin_kind is EvidenceOrigin.LEGACY_4_1
    assert first.origin_ref == "consumer_signals:R-001"
    assert first.subject_key == "asin:B076F7HM8T"
    assert ledger.get(first.evidence_id) == first
    assert ledger.list(subject_key="asin:B076F7HM8T") == [first]

    conflicting = request.model_copy(update={"text_value": "silently changed evidence"})
    with pytest.raises(ValueError, match="origin_ref"):
        ledger.ingest(conflicting)
    database.close()


def test_legacy_4_1_import_is_read_only_idempotent_and_skips_machine_predictions(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / "maotai-4.1.db"
    connection = sqlite3.connect(legacy)
    connection.executescript(
        """
        CREATE TABLE consumer_signals (
            signal_id TEXT PRIMARY KEY,
            product_id TEXT,
            source TEXT,
            signal_type TEXT,
            source_signal_id TEXT,
            rating REAL,
            original_text TEXT,
            signal_date TEXT,
            source_url TEXT,
            signal_hash TEXT,
            metadata_json TEXT,
            imported_at TEXT
        );
        CREATE TABLE analysis_runs (
            run_id TEXT PRIMARY KEY,
            product_id TEXT,
            summary TEXT
        );
        INSERT INTO consumer_signals VALUES (
            'signal-1', 'product-1', 'amazon', 'review', 'R1', 2.0,
            'Broke after two days for my large dog.', '2026-08-01T00:00:00+00:00',
            'https://www.amazon.com/dp/B076F7HM8T', 'legacy-hash',
            '{"cookie":"must-not-import","verified":true}', '2026-08-02T00:00:00+00:00'
        );
        INSERT INTO consumer_signals VALUES (
            'signal-2', 'product-1', 'amazon', 'review', 'R2', 5.0,
            'Still intact after weeks of chewing.', '2026-08-03T00:00:00+00:00',
            'https://www.amazon.com/dp/B076F7HM8T', 'legacy-hash-2',
            '{"verified":true}', '2026-08-04T00:00:00+00:00'
        );
        INSERT INTO analysis_runs VALUES (
            'analysis-1', 'product-1', 'MODEL PREDICTION MUST NOT BECOME EVIDENCE'
        );
        """
    )
    connection.commit()
    connection.close()
    before = hashlib.sha256(legacy.read_bytes()).hexdigest()

    database = _database(tmp_path)
    ledger = CanonicalEvidenceLedger(database)
    importer = Maotai41Importer(ledger)
    first = importer.import_sqlite(legacy)
    second = importer.import_sqlite(legacy)

    assert first.source_database_sha256 == before
    assert first.imported == 2
    assert first.skipped == 0
    assert second.imported == 0
    assert second.replayed == 2
    assert hashlib.sha256(legacy.read_bytes()).hexdigest() == before

    records = ledger.list(subject_key="legacy-product:product-1")
    assert len(records) == 2
    assert {item.text_value for item in records} == {
        "Broke after two days for my large dog.",
        "Still intact after weeks of chewing.",
    }
    assert all("cookie" not in item.provenance for item in records)
    assert all("MODEL PREDICTION" not in item.text_value for item in records)
    database.close()
