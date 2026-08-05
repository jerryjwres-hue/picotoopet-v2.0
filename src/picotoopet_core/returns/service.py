"""确定性本地 Return 演练、严格验证、隔离与安全投影持久化。"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any
from uuid import uuid4

from picotoopet_core.db.database import Database
from picotoopet_core.handoffs.models import HandoffRecord, HandoffStatus
from picotoopet_core.handoffs.service import HandoffService

from .models import (
    ReturnEntryKind,
    ReturnEventSummary,
    ReturnPackageEntry,
    ReturnRecord,
    ReturnStatus,
    ReturnValidationCheck,
)


class ReturnError(RuntimeError):
    """Return 验证或读取失败。"""


class ReturnConflict(ReturnError):
    """Return 幂等键或资源绑定冲突。"""


class ReturnPolicyError(ReturnError):
    """Return 操作违反 Phase 10B-A 固定安全策略。"""


class _Quarantine(ReturnError):
    """内部验证失败；只携带固定错误码，不携带不可信正文。"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ReturnValidationService:
    """Mac Core 中本地 Return 合同验证的唯一事实服务。"""

    _PROVIDER         = "local-contract-self-test"
    _MAX_ENTRIES      = 16
    _MAX_FILE_BYTES   = 64 * 1024
    _MAX_TOTAL_BYTES  = 256 * 1024
    _MAX_EVENT_COUNT  = 16
    _ZERO_DIGEST      = "0" * 64
    _EXECUTION_NOTICE = (
        "仅完成 Return 合同、哈希、事件和隔离策略验证；未运行 Provider、代码、测试、"
        "构建、diff、worktree 或 Git 写操作。"
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
            "signatures/manifest.sha256",
        }
    )
    _ALLOWED_EVENTS = frozenset(
        {
            "provider.session.started",
            "provider.progress",
            "provider.warning",
            "provider.returned",
        }
    )
    _SECRET_PATTERNS = (
        re.compile(r"authorization\s*:\s*bearer", re.IGNORECASE),
        re.compile(r"\b(?:token|password|credential)\s*[=:]", re.IGNORECASE),
        re.compile(r"-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----", re.IGNORECASE),
        re.compile(r"protected\s*(?:source|original|原件)", re.IGNORECASE),
        re.compile(r"raw\s+evidence", re.IGNORECASE),
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

    def __init__(
        self,
        database: Database,
        handoffs: HandoffService,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.database = database
        self.handoffs = handoffs
        self._clock   = clock or (lambda: datetime.now(UTC))

    def run_self_test(
        self,
        handoff_id: str,
        *,
        idempotency_key: str,
    ) -> ReturnRecord:
        """为 approved Handoff 生成并验证服务器自有的零变更 Return。"""

        key      = self._require_idempotency_key(idempotency_key)
        existing = self._existing_by_idempotency(key, handoff_id)
        if existing is not None:
            return existing
        handoff  = self._require_approved_handoff(handoff_id)
        return_id = str(uuid4())
        entries   = self.build_self_test_entries(handoff, return_id=return_id)
        return self.validate_entries(
            handoff,
            entries,
            idempotency_key=key,
            return_id=return_id,
        )

    def validate_entries(
        self,
        handoff: HandoffRecord,
        entries: Mapping[str, ReturnPackageEntry],
        *,
        idempotency_key: str,
        return_id: str | None = None,
    ) -> ReturnRecord:
        """验证内存包并只持久化安全事实；该方法不由 REST 接收任意包。"""

        key      = self._require_idempotency_key(idempotency_key)
        existing = self._existing_by_idempotency(key, handoff.handoff_id)
        if existing is not None:
            return existing
        current = self._require_approved_handoff(handoff.handoff_id)
        if (
            current.request_digest != handoff.request_digest
            or current.package_digest != handoff.package_digest
            or current.base_commit != handoff.base_commit
        ):
            raise ReturnConflict("Handoff 安全投影已变化，必须重新读取后再验证。")

        actual_return_id = return_id or str(uuid4())
        now              = self._now()
        try:
            manifest_digest, event_summaries = self._validate_entries(
                current,
                actual_return_id,
                entries,
            )
        except _Quarantine as error:
            return self._persist(
                return_id=actual_return_id,
                handoff=current,
                status=ReturnStatus.QUARANTINED,
                manifest_digest=self._safe_manifest_digest(entries),
                event_summaries=[],
                validation_checks=[
                    ReturnValidationCheck(name="return_contract", passed=False)
                ],
                quarantine_code=error.code,
                idempotency_key=key,
                occurred_at=now,
            )

        return self._persist(
            return_id=actual_return_id,
            handoff=current,
            status=ReturnStatus.CONTRACT_VALIDATED,
            manifest_digest=manifest_digest,
            event_summaries=event_summaries,
            validation_checks=[
                ReturnValidationCheck(name=name, passed=True)
                for name in self._CHECK_NAMES
            ],
            quarantine_code=None,
            idempotency_key=key,
            occurred_at=now,
        )

    def build_self_test_entries(
        self,
        handoff: HandoffRecord,
        *,
        return_id: str,
    ) -> dict[str, ReturnPackageEntry]:
        """构造不包含代码、二进制或真实 Provider 输出的固定零变更包。"""

        occurred_at = self._now().isoformat()
        events = [
            {
                "event_id": f"{return_id}-001",
                "sequence": 1,
                "occurred_at": occurred_at,
                "handoff_id": handoff.handoff_id,
                "return_id": return_id,
                "provider": self._PROVIDER,
                "event_type": "provider.session.started",
                "payload_version": "1.0.0",
                "payload": {"summary": "本地合同演练已开始。"},
            },
            {
                "event_id": f"{return_id}-002",
                "sequence": 2,
                "occurred_at": occurred_at,
                "handoff_id": handoff.handoff_id,
                "return_id": return_id,
                "provider": self._PROVIDER,
                "event_type": "provider.progress",
                "payload_version": "1.0.0",
                "payload": {"summary": "正在验证固定 Return 合同。"},
            },
            {
                "event_id": f"{return_id}-003",
                "sequence": 3,
                "occurred_at": occurred_at,
                "handoff_id": handoff.handoff_id,
                "return_id": return_id,
                "provider": self._PROVIDER,
                "event_type": "provider.returned",
                "payload_version": "1.0.0",
                "payload": {"summary": "零变更演练包已返回验证器。"},
            },
        ]
        entries: dict[str, ReturnPackageEntry] = {
            "session_events.ndjson": ReturnPackageEntry(
                content=(
                    "\n".join(self._canonical_json(item) for item in events) + "\n"
                ).encode("utf-8")
            ),
            "summary.md": ReturnPackageEntry(
                content=(
                    "# Local Return Contract Self-Test\n\n"
                    "No code, command, test, build, diff or external provider was executed.\n"
                ).encode("utf-8")
            ),
            "changed_files.json": ReturnPackageEntry(
                content=self._json_bytes(
                    {
                        "schema_version": "1.0.0",
                        "files": [],
                    }
                )
            ),
            "test_report.json": ReturnPackageEntry(
                content=self._json_bytes(
                    {
                        "schema_version": "1.0.0",
                        "tests": [
                            {
                                "command_id": "local-ci",
                                "status": "not_run",
                            }
                        ],
                    }
                )
            ),
            "build_report.json": ReturnPackageEntry(
                content=self._json_bytes(
                    {
                        "schema_version": "1.0.0",
                        "status": "not_run",
                    }
                )
            ),
            "security_report.json": ReturnPackageEntry(
                content=self._json_bytes(
                    {
                        "schema_version": "1.0.0",
                        "checks": [
                            "path_policy",
                            "file_allowlist",
                            "digest_binding",
                            "event_order",
                            "sensitive_source_excluded",
                        ],
                    }
                )
            ),
            "questions.md": ReturnPackageEntry(
                content=b"# Questions\n\nNone.\n"
            ),
        }
        manifest_digest = self._content_manifest_digest(entries)
        manifest = {
            "schema_version": "1.0.0",
            "return_id": return_id,
            "handoff_id": handoff.handoff_id,
            "request_digest": handoff.request_digest,
            "package_digest": handoff.package_digest,
            "provider": self._PROVIDER,
            "adapter_version": "phase10b-a-self-test-1",
            "external_session_id": f"local-{return_id}",
            "base_commit": handoff.base_commit,
            "stop_reason": "contract_self_test",
            "started_at": occurred_at,
            "ended_at": occurred_at,
            "usage": {
                "turns": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost": 0,
            },
            "changed_file_count": 0,
            "report_refs": {
                "changed_files": "changed_files.json",
                "tests": "test_report.json",
                "build": "build_report.json",
                "security": "security_report.json",
            },
            "manifest_digest": manifest_digest,
        }
        entries["return_manifest.json"] = ReturnPackageEntry(
            content=self._json_bytes(manifest)
        )
        self.resign_entries(entries)
        return entries

    def resign_entries(self, entries: dict[str, ReturnPackageEntry]) -> None:
        """为测试夹具重算文件清单签名；不修改 Return manifest 绑定字段。"""

        signature_path = "signatures/manifest.sha256"
        entries.pop(signature_path, None)
        lines = [
            f"{self._sha256(entry.content)}  {path}"
            for path, entry in sorted(entries.items())
        ]
        entries[signature_path] = ReturnPackageEntry(
            content=("\n".join(lines) + "\n").encode("utf-8")
        )

    def list(self, *, limit: int = 100) -> list[ReturnRecord]:
        """按创建时间倒序返回最多 100 条 Return 安全投影。"""

        bounded = max(1, min(limit, 100))
        rows = self.database.fetchall(
            "SELECT preview_json FROM returns ORDER BY created_at DESC LIMIT ?",
            (bounded,),
        )
        return [ReturnRecord.model_validate(json.loads(row["preview_json"])) for row in rows]

    def get(self, return_id: str) -> ReturnRecord:
        """读取单个 Return 安全投影。"""

        row = self.database.fetchone(
            "SELECT preview_json FROM returns WHERE return_id = ?",
            (return_id,),
        )
        if row is None:
            raise KeyError(f"Return 不存在：{return_id}")
        return ReturnRecord.model_validate(json.loads(row["preview_json"]))

    def _validate_entries(
        self,
        handoff: HandoffRecord,
        return_id: str,
        entries: Mapping[str, ReturnPackageEntry],
    ) -> tuple[str, list[ReturnEventSummary]]:
        self._validate_entry_policy(entries)
        self._validate_file_allowlist(entries)
        self._validate_sizes(entries)
        self._reject_secret_content(entries)

        manifest = self._read_json(entries, "return_manifest.json")
        self._validate_handoff_binding(manifest, handoff, return_id)
        self._validate_changed_files(entries)
        self._validate_provider_claims(entries)
        event_summaries = self._validate_events(entries, handoff, return_id)
        manifest_digest = self._validate_manifest_digest(entries, manifest)
        self._validate_sha256_coverage(entries)
        return manifest_digest, event_summaries

    def _validate_entry_policy(
        self,
        entries: Mapping[str, ReturnPackageEntry],
    ) -> None:
        if not entries or len(entries) > self._MAX_ENTRIES:
            raise _Quarantine("ENTRY_COUNT_INVALID")
        for path, entry in entries.items():
            if entry.kind is not ReturnEntryKind.FILE:
                raise _Quarantine("LINK_ENTRY_DENIED")
            if (
                not path
                or len(path) > 200
                or "\x00" in path
                or "\\" in path
                or ":" in path
                or path.startswith("/")
            ):
                raise _Quarantine("PATH_POLICY_DENIED")
            pure = PurePosixPath(path)
            if any(part in {"", ".", ".."} for part in pure.parts):
                raise _Quarantine("PATH_POLICY_DENIED")

    def _validate_file_allowlist(
        self,
        entries: Mapping[str, ReturnPackageEntry],
    ) -> None:
        if set(entries) != self._REQUIRED_FILES:
            raise _Quarantine("FILE_ALLOWLIST_DENIED")

    def _validate_sizes(self, entries: Mapping[str, ReturnPackageEntry]) -> None:
        total = 0
        for entry in entries.values():
            size = len(entry.content)
            if size > self._MAX_FILE_BYTES:
                raise _Quarantine("FILE_SIZE_LIMIT")
            total += size
        if total > self._MAX_TOTAL_BYTES:
            raise _Quarantine("PACKAGE_SIZE_LIMIT")

    def _reject_secret_content(
        self,
        entries: Mapping[str, ReturnPackageEntry],
    ) -> None:
        for entry in entries.values():
            text = entry.content.decode("utf-8", errors="ignore")
            if any(pattern.search(text) for pattern in self._SECRET_PATTERNS):
                raise _Quarantine("SECRET_CONTENT_DENIED")

    def _validate_handoff_binding(
        self,
        manifest: dict[str, Any],
        handoff: HandoffRecord,
        return_id: str,
    ) -> None:
        expected = {
            "schema_version": "1.0.0",
            "return_id": return_id,
            "handoff_id": handoff.handoff_id,
            "request_digest": handoff.request_digest,
            "package_digest": handoff.package_digest,
            "provider": self._PROVIDER,
            "base_commit": handoff.base_commit,
            "changed_file_count": 0,
        }
        if any(manifest.get(key) != value for key, value in expected.items()):
            raise _Quarantine("HANDOFF_BINDING_MISMATCH")

    def _validate_changed_files(
        self,
        entries: Mapping[str, ReturnPackageEntry],
    ) -> None:
        payload = self._read_json(entries, "changed_files.json")
        if payload.get("schema_version") != "1.0.0" or payload.get("files") != []:
            raise _Quarantine("CHANGED_FILES_DENIED")

    def _validate_provider_claims(
        self,
        entries: Mapping[str, ReturnPackageEntry],
    ) -> None:
        tests = self._read_json(entries, "test_report.json")
        build = self._read_json(entries, "build_report.json")
        test_items = tests.get("tests")
        if (
            tests.get("schema_version") != "1.0.0"
            or not isinstance(test_items, list)
            or not test_items
            or any(item.get("status") != "not_run" for item in test_items if isinstance(item, dict))
            or any(not isinstance(item, dict) for item in test_items)
            or build.get("schema_version") != "1.0.0"
            or build.get("status") != "not_run"
        ):
            raise _Quarantine("PROVIDER_CLAIM_DENIED")

    def _validate_events(
        self,
        entries: Mapping[str, ReturnPackageEntry],
        handoff: HandoffRecord,
        return_id: str,
    ) -> list[ReturnEventSummary]:
        raw_lines = entries["session_events.ndjson"].content.decode("utf-8").splitlines()
        if not raw_lines or len(raw_lines) > self._MAX_EVENT_COUNT:
            raise _Quarantine("EVENT_COUNT_INVALID")
        events: list[dict[str, Any]] = []
        try:
            for line in raw_lines:
                item = json.loads(line)
                if not isinstance(item, dict):
                    raise TypeError
                events.append(item)
        except (json.JSONDecodeError, TypeError):
            raise _Quarantine("EVENT_FORMAT_INVALID") from None

        event_ids = [item.get("event_id") for item in events]
        if len(set(event_ids)) != len(event_ids):
            raise _Quarantine("EVENT_ID_DUPLICATE")
        sequences = [item.get("sequence") for item in events]
        if sequences != list(range(1, len(events) + 1)):
            raise _Quarantine("EVENT_SEQUENCE_INVALID")

        summaries: list[ReturnEventSummary] = []
        for item in events:
            event_type = item.get("event_type")
            payload    = item.get("payload")
            summary    = payload.get("summary") if isinstance(payload, dict) else None
            if (
                event_type not in self._ALLOWED_EVENTS
                or item.get("handoff_id") != handoff.handoff_id
                or item.get("return_id") != return_id
                or item.get("provider") != self._PROVIDER
                or item.get("payload_version") != "1.0.0"
                or not isinstance(summary, str)
                or not 1 <= len(summary) <= 160
            ):
                raise _Quarantine("EVENT_CONTRACT_INVALID")
            summaries.append(
                ReturnEventSummary(
                    sequence=int(item["sequence"]),
                    event_type=str(event_type),
                    summary=summary,
                )
            )
        return summaries

    def _validate_manifest_digest(
        self,
        entries: Mapping[str, ReturnPackageEntry],
        manifest: dict[str, Any],
    ) -> str:
        expected = self._content_manifest_digest(entries)
        actual   = manifest.get("manifest_digest")
        if actual != expected:
            raise _Quarantine("MANIFEST_DIGEST_MISMATCH")
        return expected

    def _validate_sha256_coverage(
        self,
        entries: Mapping[str, ReturnPackageEntry],
    ) -> None:
        signature = entries["signatures/manifest.sha256"].content.decode("utf-8")
        actual: dict[str, str] = {}
        for line in signature.splitlines():
            if "  " not in line:
                raise _Quarantine("SHA256_MANIFEST_INVALID")
            digest, path = line.split("  ", 1)
            if path in actual or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise _Quarantine("SHA256_MANIFEST_INVALID")
            actual[path] = digest
        expected = {
            path: self._sha256(entry.content)
            for path, entry in entries.items()
            if path != "signatures/manifest.sha256"
        }
        if actual != expected:
            raise _Quarantine("SHA256_COVERAGE_MISMATCH")

    def _persist(
        self,
        *,
        return_id: str,
        handoff: HandoffRecord,
        status: ReturnStatus,
        manifest_digest: str,
        event_summaries: list[ReturnEventSummary],
        validation_checks: list[ReturnValidationCheck],
        quarantine_code: str | None,
        idempotency_key: str,
        occurred_at: datetime,
    ) -> ReturnRecord:
        preview = ReturnRecord(
            return_id=return_id,
            handoff_id=handoff.handoff_id,
            status=status,
            provider=self._PROVIDER,
            request_digest=handoff.request_digest,
            package_digest=handoff.package_digest,
            manifest_digest=manifest_digest,
            changed_file_count=0,
            event_count=len(event_summaries),
            validation_checks=validation_checks,
            event_summaries=event_summaries,
            quarantine_code=quarantine_code,
            created_at=occurred_at,
            updated_at=occurred_at,
            execution_notice=self._EXECUTION_NOTICE,
        )
        preview_json = self._canonical_json(preview.model_dump(mode="json"))
        checks_json  = self._canonical_json(
            [item.model_dump(mode="json") for item in validation_checks]
        )
        try:
            with self.database.transaction() as connection:
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
                        handoff.handoff_id,
                        status.value,
                        self._PROVIDER,
                        handoff.request_digest,
                        handoff.package_digest,
                        manifest_digest,
                        0,
                        len(event_summaries),
                        checks_json,
                        preview_json,
                        quarantine_code,
                        idempotency_key,
                        occurred_at.isoformat(),
                        occurred_at.isoformat(),
                    ),
                )
        except Exception as error:
            existing = self._existing_by_idempotency(
                idempotency_key,
                handoff.handoff_id,
            )
            if existing is not None:
                return existing
            raise ReturnConflict("Return 持久化冲突。") from error
        return preview

    def _existing_by_idempotency(
        self,
        idempotency_key: str,
        handoff_id: str,
    ) -> ReturnRecord | None:
        row = self.database.fetchone(
            "SELECT handoff_id, preview_json FROM returns WHERE idempotency_key = ?",
            (idempotency_key,),
        )
        if row is None:
            return None
        if row["handoff_id"] != handoff_id:
            raise ReturnConflict("Idempotency-Key 已绑定不同的 Handoff。")
        return ReturnRecord.model_validate(json.loads(row["preview_json"]))

    def _require_approved_handoff(self, handoff_id: str) -> HandoffRecord:
        handoff = self.handoffs.get(handoff_id)
        if handoff.status is not HandoffStatus.APPROVED:
            raise ReturnPolicyError("只有 approved Handoff 可以运行 Return 合同验证。")
        return handoff

    @staticmethod
    def _require_idempotency_key(value: str) -> str:
        key = value.strip()
        if not 1 <= len(key) <= 200 or any(ord(character) < 33 for character in key):
            raise ReturnPolicyError("Idempotency-Key 不符合固定安全格式。")
        return key

    @classmethod
    def _content_manifest_digest(
        cls,
        entries: Mapping[str, ReturnPackageEntry],
    ) -> str:
        payload = {
            "files": [
                {
                    "path": path,
                    "sha256": cls._sha256(entry.content),
                }
                for path, entry in sorted(entries.items())
                if path not in {
                    "return_manifest.json",
                    "signatures/manifest.sha256",
                }
            ]
        }
        return cls._sha256(cls._canonical_json(payload).encode("utf-8"))

    @classmethod
    def _safe_manifest_digest(
        cls,
        entries: Mapping[str, ReturnPackageEntry],
    ) -> str:
        entry = entries.get("return_manifest.json")
        if entry is None or entry.kind is not ReturnEntryKind.FILE:
            return cls._ZERO_DIGEST
        try:
            payload = json.loads(entry.content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return cls._ZERO_DIGEST
        value = payload.get("manifest_digest") if isinstance(payload, dict) else None
        return value if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) else cls._ZERO_DIGEST

    @staticmethod
    def _read_json(
        entries: Mapping[str, ReturnPackageEntry],
        path: str,
    ) -> dict[str, Any]:
        try:
            payload = json.loads(entries[path].content.decode("utf-8"))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError):
            raise _Quarantine("JSON_CONTRACT_INVALID") from None
        if not isinstance(payload, dict):
            raise _Quarantine("JSON_CONTRACT_INVALID")
        return payload

    @staticmethod
    def _canonical_json(value: Any) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def _json_bytes(cls, value: Any) -> bytes:
        return (cls._canonical_json(value) + "\n").encode("utf-8")

    @staticmethod
    def _sha256(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
