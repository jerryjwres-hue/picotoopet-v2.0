"""Read-only compatibility import from Maotai Intelligence OS 4.1 SQLite."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict

from .evidence_ledger import (
    CanonicalEvidenceCreate,
    CanonicalEvidenceLedger,
    EvidenceOrigin,
    EvidenceTrust,
)


class LegacyImportReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_database_sha256: str
    imported: int
    replayed: int
    skipped: int
    source_table: str


class Maotai41Importer:
    """Import raw evidence only; legacy analyses/predictions are never promoted to facts."""

    def __init__(self, ledger: CanonicalEvidenceLedger) -> None:
        self.ledger = ledger

    def import_sqlite(self, path: Path | str, *, limit: int = 50_000) -> LegacyImportReport:
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise ValueError("legacy database does not exist")
        if limit < 1 or limit > 200_000:
            raise ValueError("legacy import limit out of bounds")
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        uri = f"file:{quote(str(source))}?mode=ro&immutable=1"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        imported = replayed = skipped = 0
        try:
            connection.execute("PRAGMA query_only=ON")
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            if "evidence_items" in tables:
                source_table = "evidence_items"
                rows = connection.execute(
                    "SELECT * FROM evidence_items ORDER BY rowid LIMIT ?", (limit,)
                ).fetchall()
                requests = (self._from_evidence_item(row) for row in rows)
            elif "consumer_signals" in tables:
                source_table = "consumer_signals"
                rows = connection.execute(
                    "SELECT * FROM consumer_signals ORDER BY rowid LIMIT ?", (limit,)
                ).fetchall()
                requests = (self._from_consumer_signal(row) for row in rows)
            else:
                raise ValueError("legacy database contains no supported raw evidence table")

            for request in requests:
                if request is None:
                    skipped += 1
                    continue
                try:
                    existing = self.ledger.database.fetchone(
                        "SELECT evidence_id FROM canonical_evidence WHERE origin_kind = ? AND origin_ref = ?",
                        (request.origin_kind.value, request.origin_ref),
                    )
                    self.ledger.ingest(request)
                    if existing is None:
                        imported += 1
                    else:
                        replayed += 1
                except (ValueError, TypeError, json.JSONDecodeError):
                    skipped += 1
        finally:
            connection.close()
        after = hashlib.sha256(source.read_bytes()).hexdigest()
        if after != before:
            raise RuntimeError("legacy source database changed during read-only import")
        return LegacyImportReport(
            source_database_sha256=before,
            imported=imported,
            replayed=replayed,
            skipped=skipped,
            source_table=source_table,
        )

    @staticmethod
    def _from_consumer_signal(row: sqlite3.Row) -> CanonicalEvidenceCreate | None:
        text = str(row["original_text"] or "").strip()
        if not text:
            return None
        product_id = str(row["product_id"] or "unknown").strip() or "unknown"
        signal_id = str(row["signal_id"] or "").strip()
        if not signal_id:
            return None
        source = str(row["source"] or "legacy").strip()[:100] or "legacy"
        captured = Maotai41Importer._parse_time(row["signal_date"]) or Maotai41Importer._parse_time(
            row["imported_at"]
        ) or datetime.now(UTC)
        rating = row["rating"]
        return CanonicalEvidenceCreate(
            subject_key=f"legacy-product:{product_id}",
            evidence_type=str(row["signal_type"] or "consumer_signal")[:100],
            source=source,
            platform=source,
            source_url=(str(row["source_url"]).strip()[:4_000] if row["source_url"] else None),
            source_entity_id=(
                str(row["source_signal_id"]).strip()[:500]
                if row["source_signal_id"]
                else signal_id[:500]
            ),
            text_value=text[:20_000],
            numeric_value=float(rating) if rating is not None else None,
            value={"rating": float(rating)} if rating is not None else {},
            trust_level=EvidenceTrust.B,
            confidence=0.85,
            captured_at=captured,
            provenance={
                "compatibility_source": "maotai-intelligence-os-4.1",
                "legacy_table": "consumer_signals",
                "legacy_signal_id": signal_id,
                "machine_analysis_imported": False,
            },
            origin_kind=EvidenceOrigin.LEGACY_4_1,
            origin_ref=f"consumer_signals:{signal_id}",
        )

    @staticmethod
    def _from_evidence_item(row: sqlite3.Row) -> CanonicalEvidenceCreate | None:
        evidence_id = str(row["evidence_id"] or "").strip()
        if not evidence_id:
            return None
        text = str(row["text_value"] or "").strip()
        numeric = row["numeric_value"]
        if not text and numeric is None:
            return None
        product_id = str(row["product_id"] or "unknown").strip() or "unknown"
        source = str(row["source"] or "legacy").strip()[:100] or "legacy"
        platform = str(row["platform"] or source).strip()[:100] or source
        captured = Maotai41Importer._parse_time(row["captured_at"]) or datetime.now(UTC)
        trust_raw = str(row["trust_level"] or "C").strip().upper()
        trust = EvidenceTrust(trust_raw) if trust_raw in {item.value for item in EvidenceTrust} else EvidenceTrust.C
        confidence = float(row["confidence"]) if row["confidence"] is not None else 0.75
        confidence = max(0.0, min(1.0, confidence))
        return CanonicalEvidenceCreate(
            subject_key=f"legacy-product:{product_id}",
            evidence_type=str(row["evidence_type"] or "legacy_evidence")[:100],
            source=source,
            platform=platform,
            source_url=(str(row["source_url"]).strip()[:4_000] if row["source_url"] else None),
            source_entity_id=(
                str(row["source_entity_id"]).strip()[:500]
                if row["source_entity_id"]
                else evidence_id[:500]
            ),
            text_value=text[:20_000],
            numeric_value=float(numeric) if numeric is not None else None,
            value={},
            trust_level=trust,
            confidence=confidence,
            captured_at=captured,
            source_updated_at=Maotai41Importer._parse_time(row["source_updated_at"]),
            provenance={
                "compatibility_source": "maotai-intelligence-os-4.1",
                "legacy_table": "evidence_items",
                "legacy_evidence_id": evidence_id,
                "machine_analysis_imported": False,
            },
            origin_kind=EvidenceOrigin.LEGACY_4_1,
            origin_ref=f"evidence_items:{evidence_id}",
        )

    @staticmethod
    def _parse_time(value: object) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
