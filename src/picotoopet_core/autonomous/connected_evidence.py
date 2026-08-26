"""Canonical evidence intake for legacy Maotai 4.1 data and Browser Bridge captures."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote, urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from picotoopet_core.db.database import Database

from .browser_broker import BrowserCaptureEvidence, validate_browser_capture

_MAX_LEGACY_DB_BYTES = 512 * 1024 * 1024
_MAX_PRODUCTS = 10_000
_MAX_EVIDENCE = 100_000
_MAX_TEXT_CHARS = 20_000


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_hash(value: object) -> str:
    return _sha256_bytes(_json(value).encode("utf-8"))


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ConnectedProductRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    product_key: str
    title: str
    brand: str
    category: str
    origin: str
    external_ref_type: str
    external_ref_id: str
    source_url: str
    metadata: dict[str, Any]


class ConnectedEvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str
    product_key: str
    evidence_type: str
    source: str
    platform: str
    source_url: str
    source_entity_id: str
    text_value: str
    numeric_value: float | None = None
    value: dict[str, Any]
    raw_hash: str
    trust_level: str
    confidence: float
    captured_at: str
    source_updated_at: str
    origin: str
    external_ref_type: str
    external_ref_id: str
    idempotency_key: str
    provenance: dict[str, Any]


class LegacyImportRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    import_id: str
    source_sha256: str
    source_name: str
    source_size_bytes: int
    source_schema_version: int | None = None
    status: str
    products_imported: int
    evidence_imported: int
    evidence_skipped: int
    created_at: str
    completed_at: str | None = None


class BrowserCaptureRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capture_id: str
    product_key: str
    source_url: str
    platform: str
    capture_type: str
    packet_sha256: str
    evidence_count: int
    idempotency_key: str
    captured_at: str
    created_at: str


class ConnectedEvidenceRepository:
    """Mac Core-owned persistence; connected programs never write the Core DB directly."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert_product(
        self,
        *,
        product_key: str,
        title: str,
        brand: str = "",
        category: str = "",
        origin: str,
        external_ref_type: str = "",
        external_ref_id: str = "",
        source_url: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> ConnectedProductRecord:
        now = _now()
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO autonomous_products (
                    product_key, title, brand, category, origin,
                    external_ref_type, external_ref_id, source_url,
                    metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(product_key) DO UPDATE SET
                    title = CASE WHEN excluded.title <> '' THEN excluded.title ELSE autonomous_products.title END,
                    brand = CASE WHEN excluded.brand <> '' THEN excluded.brand ELSE autonomous_products.brand END,
                    category = CASE WHEN excluded.category <> '' THEN excluded.category ELSE autonomous_products.category END,
                    source_url = CASE WHEN excluded.source_url <> '' THEN excluded.source_url ELSE autonomous_products.source_url END,
                    updated_at = excluded.updated_at
                """,
                (
                    product_key,
                    title[:1000],
                    brand[:500],
                    category[:500],
                    origin[:100],
                    external_ref_type[:120],
                    external_ref_id[:500],
                    _safe_public_url_or_blank(source_url),
                    _json(dict(metadata or {})),
                    now,
                    now,
                ),
            )
        return self.get_product(product_key)

    def get_product(self, product_key: str) -> ConnectedProductRecord:
        row = self.database.fetchone(
            "SELECT * FROM autonomous_products WHERE product_key = ?",
            (product_key,),
        )
        if row is None:
            raise KeyError(f"connected product not found: {product_key}")
        return self._product(row)

    def list_products(self, *, limit: int = 200) -> list[ConnectedProductRecord]:
        bounded = max(1, min(int(limit), 1000))
        return [
            self._product(row)
            for row in self.database.fetchall(
                "SELECT * FROM autonomous_products ORDER BY updated_at DESC, product_key LIMIT ?",
                (bounded,),
            )
        ]

    def put_evidence(
        self,
        *,
        evidence_id: str,
        product_key: str,
        evidence_type: str,
        source: str,
        platform: str = "",
        source_url: str = "",
        source_entity_id: str = "",
        text_value: str = "",
        numeric_value: float | None = None,
        value: Mapping[str, Any] | None = None,
        raw_hash: str,
        trust_level: str = "E",
        confidence: float = 0.0,
        captured_at: str,
        source_updated_at: str = "",
        origin: str,
        external_ref_type: str = "",
        external_ref_id: str = "",
        idempotency_key: str,
        provenance: Mapping[str, Any] | None = None,
    ) -> tuple[ConnectedEvidenceRecord, bool]:
        existing = self.database.fetchone(
            "SELECT * FROM autonomous_evidence WHERE idempotency_key = ?",
            (idempotency_key,),
        )
        if existing is not None:
            record = self._evidence(existing)
            if record.raw_hash != raw_hash or record.product_key != product_key:
                raise ValueError("evidence idempotency key is bound to different content")
            return record, False

        safe_url = _safe_public_url_or_blank(source_url)
        safe_trust = trust_level if trust_level in {"A", "B", "C", "D", "E"} else "E"
        safe_confidence = max(0.0, min(float(confidence), 1.0))
        values = dict(value or {})
        provenance_value = dict(provenance or {})
        now = _now()
        inserted = False
        with self.database.transaction() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO autonomous_evidence (
                        evidence_id, product_key, evidence_type, source, platform,
                        source_url, source_entity_id, text_value, numeric_value,
                        value_json, raw_hash, trust_level, confidence, captured_at,
                        source_updated_at, origin, external_ref_type, external_ref_id,
                        idempotency_key, provenance_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        evidence_id[:128],
                        product_key,
                        evidence_type[:120],
                        source[:120],
                        platform[:120],
                        safe_url,
                        source_entity_id[:500],
                        text_value[:_MAX_TEXT_CHARS],
                        numeric_value,
                        _json(values),
                        raw_hash[:128],
                        safe_trust,
                        safe_confidence,
                        captured_at[:100],
                        source_updated_at[:100],
                        origin[:100],
                        external_ref_type[:120],
                        external_ref_id[:500],
                        idempotency_key[:300],
                        _json(provenance_value),
                        now,
                    ),
                )
                inserted = True
            except sqlite3.IntegrityError:
                # A stable evidence uniqueness key may already exist from another exact
                # legacy backup. Treat that as dedupe, never as a second fact.
                row = connection.execute(
                    """
                    SELECT * FROM autonomous_evidence
                    WHERE product_key = ? AND evidence_type = ? AND source = ?
                      AND source_entity_id = ? AND raw_hash = ?
                    """,
                    (product_key, evidence_type, source, source_entity_id[:500], raw_hash[:128]),
                ).fetchone()
                if row is None:
                    raise
                return self._evidence(row), False
        return self.get_evidence(evidence_id[:128]), inserted

    def get_evidence(self, evidence_id: str) -> ConnectedEvidenceRecord:
        row = self.database.fetchone(
            "SELECT * FROM autonomous_evidence WHERE evidence_id = ?",
            (evidence_id,),
        )
        if row is None:
            raise KeyError(f"connected evidence not found: {evidence_id}")
        return self._evidence(row)

    def list_evidence(
        self,
        *,
        product_key: str | None = None,
        limit: int = 500,
    ) -> list[ConnectedEvidenceRecord]:
        bounded = max(1, min(int(limit), 2000))
        if product_key is None:
            rows = self.database.fetchall(
                "SELECT * FROM autonomous_evidence ORDER BY captured_at DESC, evidence_id LIMIT ?",
                (bounded,),
            )
        else:
            rows = self.database.fetchall(
                """
                SELECT * FROM autonomous_evidence
                WHERE product_key = ?
                ORDER BY captured_at DESC, evidence_id LIMIT ?
                """,
                (product_key, bounded),
            )
        return [self._evidence(row) for row in rows]

    def count_evidence(self) -> int:
        return int(self.database.scalar("SELECT COUNT(*) FROM autonomous_evidence") or 0)

    def get_import_by_sha(self, source_sha256: str) -> LegacyImportRecord | None:
        row = self.database.fetchone(
            "SELECT * FROM autonomous_legacy_imports WHERE source_sha256 = ?",
            (source_sha256,),
        )
        return None if row is None else self._legacy_import(row)

    def start_import(
        self,
        *,
        source_sha256: str,
        source_name: str,
        source_size_bytes: int,
        source_schema_version: int | None,
    ) -> LegacyImportRecord:
        existing = self.get_import_by_sha(source_sha256)
        if existing is not None:
            return existing
        import_id = f"legacy41-{source_sha256[:24]}"
        self.database.execute(
            """
            INSERT INTO autonomous_legacy_imports (
                import_id, source_sha256, source_name, source_size_bytes,
                source_schema_version, status, products_imported, evidence_imported,
                evidence_skipped, created_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, 'running', 0, 0, 0, ?, NULL)
            """,
            (
                import_id,
                source_sha256,
                Path(source_name).name[:200],
                source_size_bytes,
                source_schema_version,
                _now(),
            ),
        )
        record = self.get_import_by_sha(source_sha256)
        assert record is not None
        return record

    def finish_import(
        self,
        import_id: str,
        *,
        status: str,
        products_imported: int,
        evidence_imported: int,
        evidence_skipped: int,
    ) -> LegacyImportRecord:
        self.database.execute(
            """
            UPDATE autonomous_legacy_imports
            SET status = ?, products_imported = ?, evidence_imported = ?,
                evidence_skipped = ?, completed_at = ?
            WHERE import_id = ?
            """,
            (
                status,
                products_imported,
                evidence_imported,
                evidence_skipped,
                _now(),
                import_id,
            ),
        )
        row = self.database.fetchone(
            "SELECT * FROM autonomous_legacy_imports WHERE import_id = ?",
            (import_id,),
        )
        if row is None:
            raise KeyError(f"legacy import not found: {import_id}")
        return self._legacy_import(row)

    def get_browser_capture_by_key(self, idempotency_key: str) -> BrowserCaptureRecord | None:
        row = self.database.fetchone(
            "SELECT * FROM autonomous_browser_captures WHERE idempotency_key = ?",
            (idempotency_key,),
        )
        return None if row is None else self._browser_capture(row)

    def record_browser_capture(
        self,
        *,
        capture_id: str,
        product_key: str,
        source_url: str,
        platform: str,
        capture_type: str,
        packet_sha256: str,
        evidence_count: int,
        idempotency_key: str,
        captured_at: str,
    ) -> BrowserCaptureRecord:
        existing = self.get_browser_capture_by_key(idempotency_key)
        if existing is not None:
            if existing.packet_sha256 != packet_sha256:
                raise ValueError("browser capture idempotency key is bound to different content")
            return existing
        self.database.execute(
            """
            INSERT INTO autonomous_browser_captures (
                capture_id, product_key, source_url, platform, capture_type,
                packet_sha256, evidence_count, idempotency_key, captured_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                capture_id,
                product_key,
                _safe_public_url_or_blank(source_url),
                platform[:120],
                capture_type[:120],
                packet_sha256,
                evidence_count,
                idempotency_key[:300],
                captured_at[:100],
                _now(),
            ),
        )
        record = self.get_browser_capture_by_key(idempotency_key)
        assert record is not None
        return record

    @staticmethod
    def _product(row) -> ConnectedProductRecord:  # type: ignore[no-untyped-def]
        return ConnectedProductRecord(
            product_key=row["product_key"],
            title=row["title"],
            brand=row["brand"],
            category=row["category"],
            origin=row["origin"],
            external_ref_type=row["external_ref_type"],
            external_ref_id=row["external_ref_id"],
            source_url=row["source_url"],
            metadata=json.loads(row["metadata_json"]),
        )

    @staticmethod
    def _evidence(row) -> ConnectedEvidenceRecord:  # type: ignore[no-untyped-def]
        return ConnectedEvidenceRecord(
            evidence_id=row["evidence_id"],
            product_key=row["product_key"],
            evidence_type=row["evidence_type"],
            source=row["source"],
            platform=row["platform"],
            source_url=row["source_url"],
            source_entity_id=row["source_entity_id"],
            text_value=row["text_value"],
            numeric_value=row["numeric_value"],
            value=json.loads(row["value_json"]),
            raw_hash=row["raw_hash"],
            trust_level=row["trust_level"],
            confidence=float(row["confidence"]),
            captured_at=row["captured_at"],
            source_updated_at=row["source_updated_at"],
            origin=row["origin"],
            external_ref_type=row["external_ref_type"],
            external_ref_id=row["external_ref_id"],
            idempotency_key=row["idempotency_key"],
            provenance=json.loads(row["provenance_json"]),
        )

    @staticmethod
    def _legacy_import(row) -> LegacyImportRecord:  # type: ignore[no-untyped-def]
        return LegacyImportRecord(
            import_id=row["import_id"],
            source_sha256=row["source_sha256"],
            source_name=row["source_name"],
            source_size_bytes=int(row["source_size_bytes"]),
            source_schema_version=row["source_schema_version"],
            status=row["status"],
            products_imported=int(row["products_imported"]),
            evidence_imported=int(row["evidence_imported"]),
            evidence_skipped=int(row["evidence_skipped"]),
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )

    @staticmethod
    def _browser_capture(row) -> BrowserCaptureRecord:  # type: ignore[no-untyped-def]
        return BrowserCaptureRecord(
            capture_id=row["capture_id"],
            product_key=row["product_key"],
            source_url=row["source_url"],
            platform=row["platform"],
            capture_type=row["capture_type"],
            packet_sha256=row["packet_sha256"],
            evidence_count=int(row["evidence_count"]),
            idempotency_key=row["idempotency_key"],
            captured_at=row["captured_at"],
            created_at=row["created_at"],
        )


class Legacy41Importer:
    """Copy trusted raw evidence from an explicitly supplied Maotai 4.1 SQLite DB."""

    def __init__(self, repository: ConnectedEvidenceRepository) -> None:
        self.repository = repository

    def import_database(self, source: Path | str, *, source_name: str | None = None) -> LegacyImportRecord:
        path = Path(source).expanduser().resolve(strict=True)
        if path.is_symlink() or not path.is_file():
            raise ValueError("legacy source must be a regular SQLite file")
        size = path.stat().st_size
        if size <= 0 or size > _MAX_LEGACY_DB_BYTES:
            raise ValueError("legacy database exceeds safe size limit")
        with path.open("rb") as handle:
            if handle.read(16) != b"SQLite format 3\x00":
                raise ValueError("legacy source is not a SQLite database")
        source_sha = _sha256_file(path)
        existing = self.repository.get_import_by_sha(source_sha)
        if existing is not None and existing.status == "completed":
            return existing

        connection = self._open_read_only(path)
        try:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "canonical_products" not in tables:
                raise ValueError("legacy database is missing canonical_products")
            if "evidence_items" not in tables and "consumer_signals" not in tables:
                raise ValueError("legacy database has no supported evidence table")
            schema_version = self._schema_version(connection, tables)
            record = existing or self.repository.start_import(
                source_sha256=source_sha,
                source_name=source_name or path.name,
                source_size_bytes=size,
                source_schema_version=schema_version,
            )
            products_imported = self._import_products(connection, source_sha, schema_version)
            evidence_imported, evidence_skipped = self._import_evidence(
                connection,
                tables=tables,
                source_sha=source_sha,
                source_name=Path(source_name or path.name).name,
                schema_version=schema_version,
            )
            return self.repository.finish_import(
                record.import_id,
                status="completed",
                products_imported=products_imported,
                evidence_imported=evidence_imported,
                evidence_skipped=evidence_skipped,
            )
        except Exception:
            record = self.repository.get_import_by_sha(source_sha)
            if record is not None and record.status != "completed":
                self.repository.finish_import(
                    record.import_id,
                    status="failed",
                    products_imported=record.products_imported,
                    evidence_imported=record.evidence_imported,
                    evidence_skipped=record.evidence_skipped,
                )
            raise
        finally:
            connection.close()

    @staticmethod
    def _open_read_only(path: Path) -> sqlite3.Connection:
        uri = f"file:{quote(path.as_posix(), safe='/:')}?mode=ro&immutable=1"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        return connection

    @staticmethod
    def _schema_version(connection: sqlite3.Connection, tables: set[str]) -> int | None:
        if "schema_migrations" not in tables:
            return None
        try:
            row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
            return None if row is None or row[0] is None else int(row[0])
        except sqlite3.DatabaseError:
            return None

    def _import_products(
        self,
        connection: sqlite3.Connection,
        source_sha: str,
        schema_version: int | None,
    ) -> int:
        rows = connection.execute(
            """
            SELECT product_id, title, COALESCE(brand, '') AS brand,
                   COALESCE(category, '') AS category
            FROM canonical_products ORDER BY product_id LIMIT ?
            """,
            (_MAX_PRODUCTS + 1,),
        ).fetchall()
        if len(rows) > _MAX_PRODUCTS:
            raise ValueError("legacy product count exceeds safe limit")
        for row in rows:
            legacy_id = str(row["product_id"])
            self.repository.upsert_product(
                product_key=f"legacy41:{legacy_id}"[:200],
                title=str(row["title"] or "")[:1000],
                brand=str(row["brand"] or "")[:500],
                category=str(row["category"] or "")[:500],
                origin="maotai41_import",
                external_ref_type="maotai41.product",
                external_ref_id=legacy_id,
                metadata={
                    "source_sha256": source_sha,
                    "source_schema_version": schema_version,
                },
            )
        return len(rows)

    def _import_evidence(
        self,
        connection: sqlite3.Connection,
        *,
        tables: set[str],
        source_sha: str,
        source_name: str,
        schema_version: int | None,
    ) -> tuple[int, int]:
        if "evidence_items" in tables:
            count = int(connection.execute("SELECT COUNT(*) FROM evidence_items").fetchone()[0])
            if count:
                return self._import_evidence_items(
                    connection,
                    source_sha=source_sha,
                    source_name=source_name,
                    schema_version=schema_version,
                    count=count,
                )
        return self._import_consumer_signals(
            connection,
            source_sha=source_sha,
            source_name=source_name,
            schema_version=schema_version,
        )

    def _import_consumer_signals(
        self,
        connection: sqlite3.Connection,
        *,
        source_sha: str,
        source_name: str,
        schema_version: int | None,
    ) -> tuple[int, int]:
        count = int(connection.execute("SELECT COUNT(*) FROM consumer_signals").fetchone()[0])
        if count > _MAX_EVIDENCE:
            raise ValueError("legacy evidence count exceeds safe limit")
        rows = connection.execute(
            """
            SELECT signal_id, product_id, source, signal_type, source_signal_id,
                   rating, original_text, signal_date, source_url, signal_hash, imported_at
            FROM consumer_signals ORDER BY signal_id
            """
        )
        imported = 0
        skipped = 0
        for row in rows:
            legacy_product_id = str(row["product_id"] or "")
            product_key = f"legacy41:{legacy_product_id}"[:200]
            try:
                self.repository.get_product(product_key)
            except KeyError:
                self.repository.upsert_product(
                    product_key=product_key,
                    title=legacy_product_id,
                    origin="maotai41_import",
                    external_ref_type="maotai41.product",
                    external_ref_id=legacy_product_id,
                )
            legacy_signal_id = str(row["signal_id"] or "")
            stable = {
                "product_id": legacy_product_id,
                "source": str(row["source"] or ""),
                "signal_type": str(row["signal_type"] or ""),
                "source_signal_id": str(row["source_signal_id"] or ""),
                "rating": row["rating"],
                "text": str(row["original_text"] or ""),
                "source_url": _safe_public_url_or_blank(str(row["source_url"] or "")),
            }
            raw_hash = _stable_hash(stable)
            _, was_inserted = self.repository.put_evidence(
                evidence_id=f"legacy41-{_stable_hash({'signal_id': legacy_signal_id})[:24]}",
                product_key=product_key,
                evidence_type=str(row["signal_type"] or "consumer_signal")[:120],
                source=str(row["source"] or "legacy")[:120],
                platform=str(row["source"] or "")[:120],
                source_url=str(row["source_url"] or ""),
                source_entity_id=str(row["source_signal_id"] or legacy_signal_id),
                text_value=str(row["original_text"] or ""),
                numeric_value=row["rating"],
                value={"rating": row["rating"]} if row["rating"] is not None else {},
                raw_hash=raw_hash,
                trust_level="D",
                confidence=0.70,
                captured_at=str(row["signal_date"] or row["imported_at"] or _now()),
                origin="maotai41_import",
                external_ref_type="maotai41.consumer_signal",
                external_ref_id=legacy_signal_id,
                idempotency_key=f"legacy41:{source_sha}:consumer_signal:{legacy_signal_id}",
                provenance={
                    "legacy_product_id": legacy_product_id,
                    "legacy_signal_id": legacy_signal_id,
                    "legacy_signal_hash": str(row["signal_hash"] or ""),
                    "source_name": Path(source_name).name[:200],
                    "source_schema_version": schema_version,
                },
            )
            if was_inserted:
                imported += 1
            else:
                skipped += 1
        return imported, skipped

    def _import_evidence_items(
        self,
        connection: sqlite3.Connection,
        *,
        source_sha: str,
        source_name: str,
        schema_version: int | None,
        count: int,
    ) -> tuple[int, int]:
        if count > _MAX_EVIDENCE:
            raise ValueError("legacy evidence count exceeds safe limit")
        rows = connection.execute(
            """
            SELECT evidence_id, product_id, evidence_type, source, platform,
                   source_url, source_entity_id, text_value, numeric_value,
                   raw_hash, trust_level, confidence, captured_at, source_updated_at
            FROM evidence_items ORDER BY evidence_id
            """
        )
        imported = 0
        skipped = 0
        for row in rows:
            legacy_product_id = str(row["product_id"] or "")
            product_key = f"legacy41:{legacy_product_id}"[:200]
            try:
                self.repository.get_product(product_key)
            except KeyError:
                self.repository.upsert_product(
                    product_key=product_key,
                    title=legacy_product_id,
                    origin="maotai41_import",
                    external_ref_type="maotai41.product",
                    external_ref_id=legacy_product_id,
                )
            legacy_evidence_id = str(row["evidence_id"] or "")
            stable = {
                "product_id": legacy_product_id,
                "evidence_type": str(row["evidence_type"] or ""),
                "source": str(row["source"] or ""),
                "source_entity_id": str(row["source_entity_id"] or ""),
                "text": str(row["text_value"] or ""),
                "numeric": row["numeric_value"],
            }
            _, was_inserted = self.repository.put_evidence(
                evidence_id=f"legacy41-{_stable_hash({'evidence_id': legacy_evidence_id})[:24]}",
                product_key=product_key,
                evidence_type=str(row["evidence_type"] or "evidence")[:120],
                source=str(row["source"] or "legacy")[:120],
                platform=str(row["platform"] or "")[:120],
                source_url=str(row["source_url"] or ""),
                source_entity_id=str(row["source_entity_id"] or legacy_evidence_id),
                text_value=str(row["text_value"] or ""),
                numeric_value=row["numeric_value"],
                raw_hash=_stable_hash(stable),
                trust_level=str(row["trust_level"] or "E"),
                confidence=float(row["confidence"] or 0.0),
                captured_at=str(row["captured_at"] or _now()),
                source_updated_at=str(row["source_updated_at"] or ""),
                origin="maotai41_import",
                external_ref_type="maotai41.evidence_item",
                external_ref_id=legacy_evidence_id,
                idempotency_key=f"legacy41:{source_sha}:evidence_item:{legacy_evidence_id}",
                provenance={
                    "legacy_product_id": legacy_product_id,
                    "legacy_evidence_id": legacy_evidence_id,
                    "legacy_raw_hash": str(row["raw_hash"] or ""),
                    "source_name": Path(source_name).name[:200],
                    "source_schema_version": schema_version,
                },
            )
            if was_inserted:
                imported += 1
            else:
                skipped += 1
        return imported, skipped


class BrowserCaptureIntake:
    """Convert one sanitized public Browser Bridge packet into canonical Core evidence."""

    def __init__(
        self,
        repository: ConnectedEvidenceRepository,
        *,
        allowed_extension_id: str | None = None,
    ) -> None:
        self.repository = repository
        self.allowed_extension_id = allowed_extension_id

    def ingest(
        self,
        packet: dict[str, object],
        *,
        idempotency_key: str,
    ) -> BrowserCaptureRecord:
        key = idempotency_key.strip()
        if not key:
            raise ValueError("idempotency key must not be empty")
        sanitized = validate_browser_capture(
            packet,
            allowed_extension_id=self.allowed_extension_id,
        )
        packet_sha = _stable_hash(sanitized.model_dump(mode="json"))
        existing = self.repository.get_browser_capture_by_key(key)
        if existing is not None:
            if existing.packet_sha256 != packet_sha:
                raise ValueError("browser capture idempotency key is bound to different content")
            return existing

        product_key = self._product_key(sanitized)
        self.repository.upsert_product(
            product_key=product_key,
            title=sanitized.title,
            origin="browser_bridge",
            external_ref_type="browser.public_page",
            external_ref_id=sanitized.source_url,
            source_url=sanitized.source_url,
            metadata={
                "domain": sanitized.domain,
                "platform": sanitized.platform,
            },
        )
        captured_at = _now()
        evidence_count = 0
        observation = {
            "title": sanitized.title,
            "observations": sanitized.observations,
        }
        if sanitized.title or sanitized.observations:
            observation_hash = _stable_hash(observation)
            _, inserted = self.repository.put_evidence(
                evidence_id=f"browser-{observation_hash[:24]}",
                product_key=product_key,
                evidence_type="browser.public_observations",
                source=sanitized.platform or "web",
                platform=sanitized.platform,
                source_url=sanitized.source_url,
                source_entity_id=sanitized.evidence_id,
                text_value=sanitized.title,
                value=sanitized.observations,
                raw_hash=observation_hash,
                trust_level="D",
                confidence=0.70,
                captured_at=captured_at,
                origin="browser_bridge",
                external_ref_type="browser.capture",
                external_ref_id=sanitized.evidence_id,
                idempotency_key=f"browser:{key}:observations",
                provenance={
                    "message_type": sanitized.message_type,
                    "domain": sanitized.domain,
                },
            )
            evidence_count += 1 if inserted else 0

        for index, signal in enumerate(sanitized.public_signals):
            signal_hash = _stable_hash(signal)
            source_entity_id = str(
                signal.get("source_id") or signal.get("stable_key") or f"signal-{index}"
            )
            signal_url = str(signal.get("source_url") or sanitized.source_url)
            _, inserted = self.repository.put_evidence(
                evidence_id=f"browser-{signal_hash[:24]}",
                product_key=product_key,
                evidence_type="consumer_signal",
                source=sanitized.platform or "web",
                platform=sanitized.platform,
                source_url=signal_url,
                source_entity_id=source_entity_id,
                text_value=str(signal.get("text") or ""),
                numeric_value=(
                    float(signal["rating"])
                    if isinstance(signal.get("rating"), (int, float))
                    else None
                ),
                value={
                    key_name: value
                    for key_name, value in signal.items()
                    if key_name in {"rating", "date", "verified", "signal_kind", "title"}
                },
                raw_hash=signal_hash,
                trust_level="D",
                confidence=0.65,
                captured_at=captured_at,
                origin="browser_bridge",
                external_ref_type="browser.public_signal",
                external_ref_id=source_entity_id,
                idempotency_key=f"browser:{key}:signal:{index}:{signal_hash[:16]}",
                provenance={
                    "capture_evidence_id": sanitized.evidence_id,
                    "message_type": sanitized.message_type,
                },
            )
            evidence_count += 1 if inserted else 0

        return self.repository.record_browser_capture(
            capture_id=f"capture-{packet_sha[:24]}",
            product_key=product_key,
            source_url=sanitized.source_url,
            platform=sanitized.platform,
            capture_type=sanitized.message_type,
            packet_sha256=packet_sha,
            evidence_count=evidence_count,
            idempotency_key=key,
            captured_at=captured_at,
        )

    @staticmethod
    def _product_key(capture: BrowserCaptureEvidence) -> str:
        stable = {
            "platform": capture.platform,
            "source_url": capture.source_url,
            "title": capture.title,
        }
        return f"browser:{_stable_hash(stable)[:24]}"


def _safe_public_url_or_blank(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlsplit(text)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        return ""
    if parsed.username is not None or parsed.password is not None:
        return ""
    hostname = parsed.hostname.casefold().rstrip(".")
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return ""
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        return ""
    return text[:4000]
