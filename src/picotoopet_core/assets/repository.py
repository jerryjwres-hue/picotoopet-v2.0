"""Persistence for trusted assets inside the existing artifacts table (no second registry)."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from picotoopet_core.db.database import Database

from .models import (
    SOURCE_KIND,
    TrustedAssetProvenanceV1,
    TrustedAssetRecordV1,
    TrustedAssetRegisterRequestV1,
    derive_managed_relpath,
    derive_scope_key,
)

_TRUSTED = "source_kind IS NOT NULL"


class TrustedAssetRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def owner_exists(self, scope_kind: str, scope_id: str) -> bool:
        table, column = (
            ("autonomous_goals", "goal_id")
            if scope_kind == "autonomous_goal"
            else ("projects", "project_id")
        )
        return (
            self.database.fetchone(f"SELECT 1 FROM {table} WHERE {column}=?", (scope_id,))
            is not None
        )

    def by_idempotency_key(self, key: str) -> TrustedAssetRecordV1 | None:
        row = self.database.fetchone(
            f"SELECT * FROM artifacts WHERE {_TRUSTED} AND idempotency_key=?", (key,)
        )
        return None if row is None else self._record(row)

    def by_scope_content(
        self, scope_key: str, sha256: str, media_type: str
    ) -> TrustedAssetRecordV1 | None:
        row = self.database.fetchone(
            f"SELECT * FROM artifacts WHERE {_TRUSTED} "
            "AND scope_key=? AND sha256=? AND media_type=?",
            (scope_key, sha256, media_type),
        )
        return None if row is None else self._record(row)

    def get(self, asset_id: str) -> TrustedAssetRecordV1 | None:
        row = self.database.fetchone(
            f"SELECT * FROM artifacts WHERE {_TRUSTED} AND artifact_id=?", (asset_id,)
        )
        return None if row is None else self._record(row)

    def list_for_scope(
        self, scope_kind: str, scope_id: str, limit: int
    ) -> list[TrustedAssetRecordV1]:
        rows = self.database.fetchall(
            f"SELECT * FROM artifacts WHERE {_TRUSTED} AND scope_kind=? AND scope_id=? "
            "ORDER BY created_at, artifact_id LIMIT ?",
            (scope_kind, scope_id, max(1, min(limit, 100))),
        )
        return [self._record(row) for row in rows]

    def insert(self, asset_id: str, request: TrustedAssetRegisterRequestV1) -> TrustedAssetRecordV1:
        scope_key = derive_scope_key(request.scope_kind, request.scope_id)
        provenance = TrustedAssetProvenanceV1(source_kind=SOURCE_KIND)
        try:
            self.database.execute(
                "INSERT INTO artifacts("
                "artifact_id,project_id,artifact_type,classification,source_path,stored_object_hash,"
                "media_type,size_bytes,sha256,is_original,cloud_policy,created_at,"
                "scope_kind,scope_id,scope_key,managed_root_id,managed_relpath,width,height,"
                "duration_ms,source_kind,provenance_json,idempotency_key) "
                "VALUES (?,?,?,?,NULL,NULL,?,?,?,1,'local_only',?,?,?,?,?,?,?,?,NULL,?,?,?)",
                (
                    asset_id,
                    request.scope_id if request.scope_kind == "project" else None,
                    "image",
                    "INTERNAL",
                    request.media_type,
                    request.size_bytes,
                    request.sha256,
                    datetime.now(UTC).isoformat(),
                    request.scope_kind,
                    request.scope_id,
                    scope_key,
                    request.managed_root_id,
                    derive_managed_relpath(request.sha256, request.media_type),
                    request.width,
                    request.height,
                    request.source_kind,
                    json.dumps(provenance.model_dump(mode="json"), sort_keys=True),
                    request.idempotency_key,
                ),
            )
        except sqlite3.IntegrityError:
            raise
        record = self.get(asset_id)
        assert record is not None
        return record

    @staticmethod
    def _record(row: sqlite3.Row) -> TrustedAssetRecordV1:
        return TrustedAssetRecordV1(
            asset_id=row["artifact_id"],
            scope_kind=row["scope_kind"],
            scope_id=row["scope_id"],
            scope_key=row["scope_key"],
            artifact_type=row["artifact_type"],
            classification=row["classification"],
            managed_root_id=row["managed_root_id"],
            managed_relpath=row["managed_relpath"],
            sha256=row["sha256"],
            size_bytes=row["size_bytes"],
            media_type=row["media_type"],
            width=row["width"],
            height=row["height"],
            duration_ms=row["duration_ms"],
            source_kind=row["source_kind"],
            provenance=json.loads(row["provenance_json"]),
            cloud_policy=row["cloud_policy"],
            created_at=row["created_at"],
        )
