"""Trusted asset registration authority (Mac Core): logical identity only, never bytes or paths."""

from __future__ import annotations

import sqlite3
from uuid import NAMESPACE_URL, uuid5

from .models import (
    TrustedAssetRecordV1,
    TrustedAssetRegisterRequestV1,
    derive_scope_key,
)
from .repository import TrustedAssetRepository

SCOPE_NOT_FOUND = "TRUSTED_ASSET_SCOPE_NOT_FOUND"
NOT_FOUND = "TRUSTED_ASSET_NOT_FOUND"
IDEMPOTENCY_CONFLICT = "TRUSTED_ASSET_IDEMPOTENCY_CONFLICT"
FACT_CONFLICT = "TRUSTED_ASSET_FACT_CONFLICT"


class TrustedAssetError(ValueError):
    """Bounded failure; message is always one of the closed codes."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _facts(record_or_request: object) -> tuple[object, ...]:
    r = record_or_request
    return (
        r.scope_kind,
        r.scope_id,
        r.sha256,
        r.size_bytes,  # type: ignore[attr-defined]
        r.media_type,
        r.width,
        r.height,  # type: ignore[attr-defined]
    )


class TrustedAssetService:
    def __init__(self, repository: TrustedAssetRepository) -> None:
        self.repository = repository

    def register(self, request: TrustedAssetRegisterRequestV1) -> TrustedAssetRecordV1:
        if not self.repository.owner_exists(request.scope_kind, request.scope_id):
            raise TrustedAssetError(SCOPE_NOT_FOUND)
        scope_key = derive_scope_key(request.scope_kind, request.scope_id)
        # Deterministic id: same scope + content always resolves to the same logical asset.
        asset_id = str(
            uuid5(
                NAMESPACE_URL, f"picotoopet:asset:{scope_key}:{request.sha256}:{request.media_type}"
            )
        )
        for _attempt in range(2):
            existing = self.repository.by_idempotency_key(request.idempotency_key)
            if existing is not None:
                if _facts(existing) != _facts(request):
                    raise TrustedAssetError(IDEMPOTENCY_CONFLICT)
                return existing
            deduped = self.repository.by_scope_content(
                scope_key, request.sha256, request.media_type
            )
            if deduped is not None:
                if _facts(deduped) != _facts(request):
                    raise TrustedAssetError(FACT_CONFLICT)
                return deduped
            try:
                return self.repository.insert(asset_id, request)
            except sqlite3.IntegrityError:
                continue  # concurrent registration won; re-read through the idempotent paths
        raise TrustedAssetError(FACT_CONFLICT)

    def get(
        self,
        asset_id: str,
        *,
        scope_kind: str | None = None,
        scope_id: str | None = None,
    ) -> TrustedAssetRecordV1:
        record = self.repository.get(asset_id)
        if record is None:
            raise TrustedAssetError(NOT_FOUND)
        if (scope_kind, scope_id) != (None, None) and (record.scope_kind, record.scope_id) != (
            scope_kind,
            scope_id,
        ):
            # Cross-scope probes are indistinguishable from absence.
            raise TrustedAssetError(NOT_FOUND)
        return record

    def list(self, scope_kind: str, scope_id: str, limit: int = 50) -> list[TrustedAssetRecordV1]:
        if not self.repository.owner_exists(scope_kind, scope_id):
            raise TrustedAssetError(SCOPE_NOT_FOUND)
        return self.repository.list_for_scope(scope_kind, scope_id, limit)
