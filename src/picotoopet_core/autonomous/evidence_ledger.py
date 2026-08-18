"""Canonical, replay-safe evidence ledger owned by Mac Core."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from picotoopet_core.db.database import Database


_SCHEMA_020 = """
CREATE TABLE IF NOT EXISTS canonical_evidence (
    evidence_id TEXT PRIMARY KEY,
    goal_id TEXT,
    subject_key TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    source TEXT NOT NULL,
    platform TEXT NOT NULL,
    source_url TEXT,
    source_entity_id TEXT,
    text_value TEXT NOT NULL,
    numeric_value REAL,
    value_json TEXT NOT NULL,
    raw_hash TEXT NOT NULL,
    trust_level TEXT NOT NULL,
    confidence REAL NOT NULL,
    captured_at TEXT NOT NULL,
    source_updated_at TEXT,
    provenance_json TEXT NOT NULL,
    origin_kind TEXT NOT NULL,
    origin_ref TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(origin_kind, origin_ref),
    CHECK(length(raw_hash) = 64),
    CHECK(confidence >= 0.0 AND confidence <= 1.0)
);
CREATE INDEX IF NOT EXISTS idx_canonical_evidence_subject
    ON canonical_evidence(subject_key, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_canonical_evidence_goal
    ON canonical_evidence(goal_id, captured_at DESC);
"""


class EvidenceOrigin(StrEnum):
    LEGACY_4_1 = "legacy_4_1"
    BROWSER_BRIDGE = "browser_bridge"
    RESEARCH_GATEWAY = "research_gateway"
    MANUAL = "manual"


class EvidenceTrust(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"


class CanonicalEvidenceCreate(BaseModel):
    """Input to Core-owned evidence ingestion; no caller-controlled evidence ID/hash."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    goal_id: str | None = Field(default=None, max_length=128)
    subject_key: str = Field(min_length=1, max_length=500)
    evidence_type: str = Field(min_length=1, max_length=100)
    source: str = Field(min_length=1, max_length=100)
    platform: str = Field(min_length=1, max_length=100)
    source_url: str | None = Field(default=None, max_length=4_000)
    source_entity_id: str | None = Field(default=None, max_length=500)
    text_value: str = Field(default="", max_length=20_000)
    numeric_value: float | None = None
    value: dict[str, Any] = Field(default_factory=dict)
    trust_level: EvidenceTrust
    confidence: float = Field(ge=0.0, le=1.0)
    captured_at: datetime
    source_updated_at: datetime | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    origin_kind: EvidenceOrigin
    origin_ref: str = Field(min_length=1, max_length=1_000)

    @field_validator("captured_at", "source_updated_at")
    @classmethod
    def require_aware_datetime(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("evidence timestamps must be timezone-aware")
        return value


class CanonicalEvidenceRecord(CanonicalEvidenceCreate):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str
    raw_hash: str
    created_at: datetime


class CanonicalEvidenceLedger:
    """Persist evidence only in the canonical Mac Core SQLite database."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self.database.transaction() as connection:
            connection.executescript(_SCHEMA_020)
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (20, datetime.now(UTC).isoformat()),
            )

    def ingest(self, request: CanonicalEvidenceCreate) -> CanonicalEvidenceRecord:
        raw_hash = self._raw_hash(request)
        existing = self.database.fetchone(
            "SELECT * FROM canonical_evidence WHERE origin_kind = ? AND origin_ref = ?",
            (request.origin_kind.value, request.origin_ref),
        )
        if existing is not None:
            record = self._row(existing)
            if record.raw_hash != raw_hash:
                raise ValueError("origin_ref already exists with different evidence content")
            return record

        stable_id = hashlib.sha256(
            f"{request.origin_kind.value}\0{request.origin_ref}\0{raw_hash}".encode("utf-8")
        ).hexdigest()[:24]
        evidence_id = f"evidence-{stable_id}"
        created_at = datetime.now(UTC)
        value_json = json.dumps(
            request.value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        provenance_json = json.dumps(
            request.provenance,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO canonical_evidence(
                    evidence_id, goal_id, subject_key, evidence_type, source, platform,
                    source_url, source_entity_id, text_value, numeric_value, value_json,
                    raw_hash, trust_level, confidence, captured_at, source_updated_at,
                    provenance_json, origin_kind, origin_ref, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_id,
                    request.goal_id,
                    request.subject_key,
                    request.evidence_type,
                    request.source,
                    request.platform,
                    request.source_url,
                    request.source_entity_id,
                    request.text_value,
                    request.numeric_value,
                    value_json,
                    raw_hash,
                    request.trust_level.value,
                    request.confidence,
                    request.captured_at.astimezone(UTC).isoformat(),
                    (
                        request.source_updated_at.astimezone(UTC).isoformat()
                        if request.source_updated_at is not None
                        else None
                    ),
                    provenance_json,
                    request.origin_kind.value,
                    request.origin_ref,
                    created_at.isoformat(),
                ),
            )
        return self.get(evidence_id)

    def get(self, evidence_id: str) -> CanonicalEvidenceRecord:
        row = self.database.fetchone(
            "SELECT * FROM canonical_evidence WHERE evidence_id = ?",
            (evidence_id,),
        )
        if row is None:
            raise KeyError(f"evidence not found: {evidence_id}")
        return self._row(row)

    def list(
        self,
        *,
        goal_id: str | None = None,
        subject_key: str | None = None,
        limit: int = 500,
    ) -> list[CanonicalEvidenceRecord]:
        if limit < 1 or limit > 5_000:
            raise ValueError("evidence list limit out of bounds")
        clauses: list[str] = []
        parameters: list[object] = []
        if goal_id is not None:
            clauses.append("goal_id = ?")
            parameters.append(goal_id)
        if subject_key is not None:
            clauses.append("subject_key = ?")
            parameters.append(subject_key)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        parameters.append(limit)
        rows = self.database.fetchall(
            f"SELECT * FROM canonical_evidence{where} ORDER BY captured_at DESC, evidence_id LIMIT ?",
            parameters,
        )
        return [self._row(row) for row in rows]

    @staticmethod
    def _raw_hash(request: CanonicalEvidenceCreate) -> str:
        if request.text_value:
            content = request.text_value.encode("utf-8")
        else:
            content = json.dumps(
                {"numeric_value": request.numeric_value, "value": request.value},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def _row(row: Any) -> CanonicalEvidenceRecord:
        return CanonicalEvidenceRecord(
            evidence_id=row["evidence_id"],
            goal_id=row["goal_id"],
            subject_key=row["subject_key"],
            evidence_type=row["evidence_type"],
            source=row["source"],
            platform=row["platform"],
            source_url=row["source_url"],
            source_entity_id=row["source_entity_id"],
            text_value=row["text_value"],
            numeric_value=row["numeric_value"],
            value=json.loads(row["value_json"]),
            raw_hash=row["raw_hash"],
            trust_level=EvidenceTrust(row["trust_level"]),
            confidence=float(row["confidence"]),
            captured_at=datetime.fromisoformat(row["captured_at"]),
            source_updated_at=(
                datetime.fromisoformat(row["source_updated_at"])
                if row["source_updated_at"]
                else None
            ),
            provenance=json.loads(row["provenance_json"]),
            origin_kind=EvidenceOrigin(row["origin_kind"]),
            origin_ref=row["origin_ref"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
