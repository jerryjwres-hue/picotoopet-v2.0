"""固定 Mock Dev Broker Return 的独立安全策略与持久化。"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any

from picotoopet_core.handoffs.models import HandoffRecord, HandoffStatus

from .models import (
    ReturnEntryKind,
    ReturnEventSummary,
    ReturnPackageEntry,
    ReturnRecord,
    ReturnStatus,
    ReturnValidationCheck,
)
from .service import ReturnConflict, ReturnPolicyError, ReturnValidationService


_PROVIDER         = "local-mock-dev-broker"
_MAX_ENTRIES      = 10
_MAX_FILE_BYTES   = 32 * 1024
_MAX_TOTAL_BYTES  = 128 * 1024
_ZERO_DIGEST      = "0" * 64
_EXECUTION_NOTICE = (
    "仅完成固定 Mock Provider 沙盒、进程边界和 Return 合同验证；未调用真实 Provider，"
    "未运行项目测试、构建、Git worktree、PR、merge 或发布。"
)
_REQUIRED_FILES = frozenset(
    {
        "return_manifest.json",
        "session_events.ndjson",
        "summary.md",
        "changed_files.json",
        "test_report.json",
        "build_report.json",
        "security_report.json",
        "questions.md",
        "changes/docs/mock-provider-proof.txt",
        "signatures/manifest.sha256",
    }
)
_ALLOWED_EVENTS = (
    "broker.started",
    "broker.sandbox.ready",
    "provider.returned",
    "broker.return.submitted",
)
_CHECK_NAMES = (
    "entry_policy",
    "file_allowlist",
    "secret_scan",
    "handoff_binding",
    "changed_file_policy",
    "provider_claim_policy",
    "event_stream",
    "manifest_digest",
    "sha256_coverage",
)
_SECRET_PATTERNS = (
    re.compile(r"authorization\s*:\s*bearer", re.IGNORECASE),
    re.compile(r"\b(?:token|password|credential)\s*[=:]", re.IGNORECASE),
    re.compile(r"-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"protected\s*(?:source|original|原件)", re.IGNORECASE),
    re.compile(r"raw\s+evidence", re.IGNORECASE),
)


class _MockQuarantine(RuntimeError):
    """只携带固定隔离错误码，不携带不可信正文。"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def validate_mock_broker_return(
    service: ReturnValidationService,
    handoff: HandoffRecord,
    entries: Mapping[str, ReturnPackageEntry],
    *,
    session_id: str,
    return_id: str,
    sandbox_digest: str,
    idempotency_key: str,
) -> ReturnRecord:
    """验证固定 Mock Broker Return，并保持零变更自测策略不变。"""

    key      = _require_idempotency_key(idempotency_key)
    existing = _existing(service, key, handoff.handoff_id)
    if existing is not None:
        return existing
    current = service.handoffs.get(handoff.handoff_id)
    if current.status is not HandoffStatus.APPROVED:
        raise ReturnPolicyError("只有 approved Handoff 可以验证 Mock Broker Return。")
    if (
        current.request_digest != handoff.request_digest
        or current.package_digest != handoff.package_digest
        or current.base_commit != handoff.base_commit
    ):
        raise ReturnConflict("Handoff 安全投影已变化，必须重新读取后再验证。")

    occurred_at = service._now()
    try:
        manifest_digest, event_summaries = _validate_entries(
            current,
            entries,
            session_id=session_id,
            return_id=return_id,
            sandbox_digest=sandbox_digest,
        )
        status            = ReturnStatus.CONTRACT_VALIDATED
        quarantine_code   = None
        validation_checks = [
            ReturnValidationCheck(name=name, passed=True)
            for name in _CHECK_NAMES
        ]
    except _MockQuarantine as error:
        manifest_digest   = _safe_manifest_digest(entries)
        event_summaries   = []
        status            = ReturnStatus.QUARANTINED
        quarantine_code   = error.code
        validation_checks = [
            ReturnValidationCheck(name="mock_broker_contract", passed=False)
        ]

    preview = ReturnRecord(
        return_id=return_id,
        handoff_id=current.handoff_id,
        status=status,
        provider=_PROVIDER,
        request_digest=current.request_digest,
        package_digest=current.package_digest,
        manifest_digest=manifest_digest,
        changed_file_count=1,
        event_count=len(event_summaries),
        validation_checks=validation_checks,
        event_summaries=event_summaries,
        quarantine_code=quarantine_code,
        created_at=occurred_at,
        updated_at=occurred_at,
        execution_notice=_EXECUTION_NOTICE,
    )
    preview_json = _canonical_json(preview.model_dump(mode="json"))
    checks_json  = _canonical_json(
        [item.model_dump(mode="json") for item in validation_checks]
    )
    try:
        with service.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO returns (
                    return_id, handoff_id, status, provider, request_digest,
                    package_digest, manifest_digest, changed_file_count,
                    event_count, validation_checks_json, preview_json,
                    quarantine_code, idempotency_key, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    return_id,
                    current.handoff_id,
                    status.value,
                    _PROVIDER,
                    current.request_digest,
                    current.package_digest,
                    manifest_digest,
                    1,
                    len(event_summaries),
                    checks_json,
                    preview_json,
                    quarantine_code,
                    key,
                    occurred_at.isoformat(),
                    occurred_at.isoformat(),
                ),
            )
    except Exception as error:
        existing = _existing(service, key, current.handoff_id)
        if existing is not None:
            return existing
        raise ReturnConflict("Mock Broker Return 持久化冲突。") from error
    return preview


def _validate_entries(
    handoff: HandoffRecord,
    entries: Mapping[str, ReturnPackageEntry],
    *,
    session_id: str,
    return_id: str,
    sandbox_digest: str,
) -> tuple[str, list[ReturnEventSummary]]:
    _validate_entry_policy(entries)
    if set(entries) != _REQUIRED_FILES:
        raise _MockQuarantine("FILE_ALLOWLIST_DENIED")
    _validate_sizes(entries)
    _reject_secret_content(entries)

    manifest = _read_json(entries, "return_manifest.json")
    expected = {
        "schema_version": "1.0.0",
        "session_id": session_id,
        "return_id": return_id,
        "handoff_id": handoff.handoff_id,
        "request_digest": handoff.request_digest,
        "package_digest": handoff.package_digest,
        "provider": _PROVIDER,
        "base_commit": handoff.base_commit,
        "sandbox_digest": sandbox_digest,
        "changed_file_count": 1,
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise _MockQuarantine("HANDOFF_BINDING_MISMATCH")

    proof = entries["changes/docs/mock-provider-proof.txt"].content
    changed = _read_json(entries, "changed_files.json")
    expected_changed = {
        "schema_version": "1.0.0",
        "files": [
            {
                "path": "docs/mock-provider-proof.txt",
                "change_type": "added",
                "sha256": _sha256(proof),
            }
        ],
    }
    if changed != expected_changed:
        raise _MockQuarantine("CHANGED_FILES_DENIED")

    _validate_provider_claims(entries)
    event_summaries = _validate_events(
        entries,
        handoff,
        session_id=session_id,
        return_id=return_id,
    )
    manifest_digest = _validate_manifest_digest(entries, manifest)
    _validate_sha256_coverage(entries)
    return manifest_digest, event_summaries


def _validate_entry_policy(entries: Mapping[str, ReturnPackageEntry]) -> None:
    if len(entries) != _MAX_ENTRIES:
        raise _MockQuarantine("ENTRY_COUNT_INVALID")
    for path, entry in entries.items():
        if entry.kind is not ReturnEntryKind.FILE:
            raise _MockQuarantine("LINK_ENTRY_DENIED")
        if (
            not path
            or len(path) > 200
            or "\x00" in path
            or "\\" in path
            or ":" in path
            or path.startswith("/")
        ):
            raise _MockQuarantine("PATH_POLICY_DENIED")
        pure = PurePosixPath(path)
        if any(part in {"", ".", ".."} for part in pure.parts):
            raise _MockQuarantine("PATH_POLICY_DENIED")


def _validate_sizes(entries: Mapping[str, ReturnPackageEntry]) -> None:
    total = 0
    for entry in entries.values():
        size = len(entry.content)
        if size > _MAX_FILE_BYTES:
            raise _MockQuarantine("FILE_SIZE_LIMIT")
        total += size
    if total > _MAX_TOTAL_BYTES:
        raise _MockQuarantine("PACKAGE_SIZE_LIMIT")


def _reject_secret_content(entries: Mapping[str, ReturnPackageEntry]) -> None:
    for entry in entries.values():
        try:
            text = entry.content.decode("utf-8")
        except UnicodeDecodeError:
            raise _MockQuarantine("TEXT_CONTENT_REQUIRED") from None
        if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
            raise _MockQuarantine("SECRET_CONTENT_DENIED")


def _validate_provider_claims(entries: Mapping[str, ReturnPackageEntry]) -> None:
    tests      = _read_json(entries, "test_report.json")
    build      = _read_json(entries, "build_report.json")
    test_items = tests.get("tests")
    if (
        tests.get("schema_version") != "1.0.0"
        or not isinstance(test_items, list)
        or not test_items
        or any(not isinstance(item, dict) for item in test_items)
        or any(item.get("status") != "not_run" for item in test_items)
        or build.get("schema_version") != "1.0.0"
        or build.get("status") != "not_run"
    ):
        raise _MockQuarantine("PROVIDER_CLAIM_DENIED")


def _validate_events(
    entries: Mapping[str, ReturnPackageEntry],
    handoff: HandoffRecord,
    *,
    session_id: str,
    return_id: str,
) -> list[ReturnEventSummary]:
    raw_lines = entries["session_events.ndjson"].content.decode("utf-8").splitlines()
    if len(raw_lines) != len(_ALLOWED_EVENTS):
        raise _MockQuarantine("EVENT_COUNT_INVALID")
    try:
        events = [json.loads(line) for line in raw_lines]
    except json.JSONDecodeError:
        raise _MockQuarantine("EVENT_FORMAT_INVALID") from None
    if any(not isinstance(item, dict) for item in events):
        raise _MockQuarantine("EVENT_FORMAT_INVALID")
    event_ids = [item.get("event_id") for item in events]
    if len(set(event_ids)) != len(event_ids):
        raise _MockQuarantine("EVENT_ID_DUPLICATE")
    if [item.get("sequence") for item in events] != [1, 2, 3, 4]:
        raise _MockQuarantine("EVENT_SEQUENCE_INVALID")

    summaries: list[ReturnEventSummary] = []
    for index, item in enumerate(events):
        payload = item.get("payload")
        summary = payload.get("summary") if isinstance(payload, dict) else None
        if (
            item.get("event_type") != _ALLOWED_EVENTS[index]
            or item.get("session_id") != session_id
            or item.get("handoff_id") != handoff.handoff_id
            or item.get("return_id") != return_id
            or item.get("provider") != _PROVIDER
            or item.get("payload_version") != "1.0.0"
            or not isinstance(summary, str)
            or not 1 <= len(summary) <= 160
        ):
            raise _MockQuarantine("EVENT_CONTRACT_INVALID")
        summaries.append(
            ReturnEventSummary(
                sequence=index + 1,
                event_type=_ALLOWED_EVENTS[index],
                summary=summary,
            )
        )
    return summaries


def _validate_manifest_digest(
    entries: Mapping[str, ReturnPackageEntry],
    manifest: dict[str, Any],
) -> str:
    expected = _content_manifest_digest(entries)
    if manifest.get("manifest_digest") != expected:
        raise _MockQuarantine("MANIFEST_DIGEST_MISMATCH")
    return expected


def _validate_sha256_coverage(entries: Mapping[str, ReturnPackageEntry]) -> None:
    signature = entries["signatures/manifest.sha256"].content.decode("utf-8")
    actual: dict[str, str] = {}
    for line in signature.splitlines():
        if "  " not in line:
            raise _MockQuarantine("SHA256_MANIFEST_INVALID")
        digest, path = line.split("  ", 1)
        if path in actual or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise _MockQuarantine("SHA256_MANIFEST_INVALID")
        actual[path] = digest
    expected = {
        path: _sha256(entry.content)
        for path, entry in entries.items()
        if path != "signatures/manifest.sha256"
    }
    if actual != expected:
        raise _MockQuarantine("SHA256_COVERAGE_MISMATCH")


def _existing(
    service: ReturnValidationService,
    idempotency_key: str,
    handoff_id: str,
) -> ReturnRecord | None:
    row = service.database.fetchone(
        "SELECT handoff_id, preview_json FROM returns WHERE idempotency_key = ?",
        (idempotency_key,),
    )
    if row is None:
        return None
    if row["handoff_id"] != handoff_id:
        raise ReturnConflict("Idempotency-Key 已绑定不同的 Handoff。")
    return ReturnRecord.model_validate(json.loads(row["preview_json"]))


def _require_idempotency_key(value: str) -> str:
    key = value.strip()
    if not 1 <= len(key) <= 200 or any(ord(character) < 33 for character in key):
        raise ReturnPolicyError("Idempotency-Key 不符合固定安全格式。")
    return key


def _content_manifest_digest(entries: Mapping[str, ReturnPackageEntry]) -> str:
    payload = {
        "files": [
            {"path": path, "sha256": _sha256(entry.content)}
            for path, entry in sorted(entries.items())
            if path not in {"return_manifest.json", "signatures/manifest.sha256"}
        ]
    }
    return _sha256(_canonical_json(payload).encode("utf-8"))


def _safe_manifest_digest(entries: Mapping[str, ReturnPackageEntry]) -> str:
    entry = entries.get("return_manifest.json")
    if entry is None or entry.kind is not ReturnEntryKind.FILE:
        return _ZERO_DIGEST
    try:
        payload = json.loads(entry.content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _ZERO_DIGEST
    value = payload.get("manifest_digest") if isinstance(payload, dict) else None
    return (
        value
        if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
        else _ZERO_DIGEST
    )


def _read_json(
    entries: Mapping[str, ReturnPackageEntry],
    path: str,
) -> dict[str, Any]:
    try:
        payload = json.loads(entries[path].content.decode("utf-8"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError):
        raise _MockQuarantine("JSON_CONTRACT_INVALID") from None
    if not isinstance(payload, dict):
        raise _MockQuarantine("JSON_CONTRACT_INVALID")
    return payload


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
