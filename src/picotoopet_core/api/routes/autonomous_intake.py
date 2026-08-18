"""Authenticated connected-program evidence intake routes."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Request, status

from picotoopet_core.api.errors import ApiError
from picotoopet_core.autonomous.connected_evidence import (
    BrowserCaptureIntake,
    BrowserCaptureRecord,
    ConnectedEvidenceRepository,
    Legacy41Importer,
    LegacyImportRecord,
)
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])
_MAX_LEGACY_UPLOAD_BYTES = 512 * 1024 * 1024


def _repository(request: Request) -> ConnectedEvidenceRepository:
    return ConnectedEvidenceRepository(request.app.state.services.database)


@router.post(
    "/autonomous/browser-captures",
    response_model=BrowserCaptureRecord,
    status_code=status.HTTP_201_CREATED,
)
def ingest_browser_capture(
    packet: dict[str, object],
    request: Request,
    idempotency_key: str = Header(
        min_length=1,
        max_length=300,
        alias="Idempotency-Key",
    ),
) -> BrowserCaptureRecord:
    """Persist only the sanitized public projection of one Browser Bridge packet."""

    try:
        return BrowserCaptureIntake(_repository(request)).ingest(
            packet,
            idempotency_key=idempotency_key,
        )
    except ValueError as error:
        conflict = "idempotency" in str(error).casefold()
        raise ApiError(
            status_code=409 if conflict else 400,
            code="BROWSER_CAPTURE_CONFLICT" if conflict else "BROWSER_CAPTURE_REJECTED",
            message=(
                "该采集幂等键已绑定到不同内容。"
                if conflict
                else "浏览器采集包未通过只读公共数据安全校验。"
            ),
            retryable=False,
        ) from error


@router.post(
    "/autonomous/legacy-4.1/import",
    response_model=LegacyImportRecord,
    status_code=status.HTTP_201_CREATED,
)
async def import_legacy_41_database(
    request: Request,
    source_name: str = Header(
        default="Maotai-4.1.db",
        min_length=1,
        max_length=200,
        alias="X-Picotoo-Source-Name",
    ),
) -> LegacyImportRecord:
    """Stream one user-selected legacy DB into managed staging, import read-only, then delete the copy."""

    content_type = str(request.headers.get("content-type") or "").split(";", 1)[0].strip().casefold()
    if content_type not in {"application/octet-stream", "application/vnd.sqlite3", "application/x-sqlite3"}:
        raise ApiError(
            status_code=415,
            code="LEGACY_IMPORT_CONTENT_TYPE",
            message="旧版数据库导入只接受 SQLite 二进制文件。",
            retryable=False,
        )

    paths = request.app.state.services.settings.paths
    staging_root = paths.autonomous_staging_dir / "legacy-4.1-imports"
    staging_root.mkdir(parents=True, exist_ok=True)
    temporary = staging_root / f".upload-{uuid4().hex}.sqlite"
    total = 0
    try:
        with temporary.open("xb") as handle:
            async for chunk in request.stream():
                if not chunk:
                    continue
                total += len(chunk)
                if total > _MAX_LEGACY_UPLOAD_BYTES:
                    raise ApiError(
                        status_code=413,
                        code="LEGACY_IMPORT_TOO_LARGE",
                        message="旧版数据库超过安全导入上限。",
                        retryable=False,
                    )
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if total == 0:
            raise ApiError(
                status_code=400,
                code="LEGACY_IMPORT_EMPTY",
                message="旧版数据库文件为空。",
                retryable=False,
            )
        try:
            return Legacy41Importer(_repository(request)).import_database(
                temporary,
                source_name=Path(source_name).name,
            )
        except (OSError, ValueError) as error:
            raise ApiError(
                status_code=400,
                code="LEGACY_IMPORT_REJECTED",
                message="旧版 4.1 数据库未通过只读兼容导入校验。",
                retryable=False,
            ) from error
    finally:
        temporary.unlink(missing_ok=True)
        try:
            staging_root.rmdir()
        except OSError:
            pass
