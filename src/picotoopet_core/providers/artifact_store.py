"""不可变 Provider Return Artifact Store。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .change_set import NormalizedChange, ProviderChangeInput

MAX_CHANGED_FILES = 5
MAX_FILE_BYTES = 64 * 1024
MAX_PAYLOAD_BYTES = 256 * 1024
MAX_REVIEW_DIFF_BYTES = 128 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RETURN_ID = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:/")
_SECRET_PATTERNS = (
    re.compile(r"(?i)authorization\s*[:=]\s*bearer\s+\S+"),
    re.compile(r"(?i)api[_-]?key\s*[:=]\s*\S+"),
    re.compile(r"(?i)token\s*[:=]\s*\S+"),
    re.compile(r"(?i)password\s*[:=]\s*\S+"),
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
)


class ProviderArtifactError(ValueError):
    """固定错误码的 Artifact 安全失败。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class StoredProviderArtifact:
    """已通过本地完整性校验的 Artifact。"""

    return_id: str
    change_set_digest: str
    review_diff_digest: str
    changed_file_count: int
    payload_bytes: int
    changes: tuple[NormalizedChange, ...]
    review_diff: str


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: object) -> bytes:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (text + "\n").encode("utf-8")


def _safe_relative_path(value: str) -> str:
    if not value or "\x00" in value or "\\" in value:
        raise ProviderArtifactError("ADOPTION_PATH_POLICY")
    if value.startswith("/") or _DRIVE_PREFIX.match(value):
        raise ProviderArtifactError("ADOPTION_PATH_POLICY")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ProviderArtifactError("ADOPTION_PATH_POLICY")
    path = PurePosixPath(value)
    normalized = path.as_posix()
    if normalized != value or path.is_absolute():
        raise ProviderArtifactError("ADOPTION_PATH_POLICY")
    return normalized


def _reject_secret(text: str) -> None:
    if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
        raise ProviderArtifactError("ADOPTION_SECRET_REJECTED")


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _manifest_bytes(entries: Iterable[tuple[str, bytes]]) -> bytes:
    lines = [f"{_sha256(data)}  {name}" for name, data in sorted(entries)]
    return ("\n".join(lines) + "\n").encode("utf-8")


class ProviderReturnArtifactStore:
    """只接受有界文本变更，并以临时目录原子切换为不可变 Artifact。"""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        *,
        return_id: str,
        base_commit: str,
        changes: list[ProviderChangeInput],
        review_diff: str,
    ) -> StoredProviderArtifact:
        """验证、规范化并原子写入一个 Return Artifact。"""

        if not _RETURN_ID.fullmatch(return_id):
            raise ProviderArtifactError("ADOPTION_ARTIFACT_INVALID")
        if not re.fullmatch(r"[0-9a-f]{40,64}", base_commit):
            raise ProviderArtifactError("ADOPTION_BASE_MISMATCH")
        if len(changes) > MAX_CHANGED_FILES:
            raise ProviderArtifactError("ADOPTION_TOO_MANY_FILES")

        diff_bytes = review_diff.encode("utf-8")
        if len(diff_bytes) > MAX_REVIEW_DIFF_BYTES:
            raise ProviderArtifactError("ADOPTION_DIFF_TOO_LARGE")
        _reject_secret(review_diff)

        normalized: list[NormalizedChange] = []
        payloads: list[tuple[str, bytes]] = []
        seen_paths: set[str] = set()
        payload_bytes = 0
        payload_index = 0
        for change in changes:
            safe_path = _safe_relative_path(change.path)
            if safe_path in seen_paths:
                raise ProviderArtifactError("ADOPTION_CHANGE_INVALID")
            seen_paths.add(safe_path)

            if change.operation == "add":
                if change.base_sha256 is not None or change.result_text is None:
                    raise ProviderArtifactError("ADOPTION_CHANGE_INVALID")
            elif change.operation == "modify":
                if not change.base_sha256 or not _SHA256.fullmatch(change.base_sha256):
                    raise ProviderArtifactError("ADOPTION_CHANGE_INVALID")
                if change.result_text is None:
                    raise ProviderArtifactError("ADOPTION_CHANGE_INVALID")
            elif change.operation == "delete":
                if not change.base_sha256 or not _SHA256.fullmatch(change.base_sha256):
                    raise ProviderArtifactError("ADOPTION_CHANGE_INVALID")
                if change.result_text is not None:
                    raise ProviderArtifactError("ADOPTION_CHANGE_INVALID")
            else:
                raise ProviderArtifactError("ADOPTION_CHANGE_INVALID")

            if change.result_text is None:
                normalized.append(
                    NormalizedChange(
                        operation="delete",
                        path=safe_path,
                        base_sha256=change.base_sha256,
                        result_sha256=None,
                        size_bytes=0,
                        payload_name=None,
                    )
                )
                continue

            _reject_secret(change.result_text)
            data = change.result_text.encode("utf-8")
            if len(data) > MAX_FILE_BYTES:
                raise ProviderArtifactError("ADOPTION_FILE_TOO_LARGE")
            payload_bytes += len(data)
            if payload_bytes > MAX_PAYLOAD_BYTES:
                raise ProviderArtifactError("ADOPTION_PAYLOAD_TOO_LARGE")
            payload_name = f"payload/{payload_index:03d}.txt"
            payload_index += 1
            payloads.append((payload_name, data))
            normalized.append(
                NormalizedChange(
                    operation=change.operation,
                    path=safe_path,
                    base_sha256=change.base_sha256,
                    result_sha256=_sha256(data),
                    size_bytes=len(data),
                    payload_name=payload_name,
                )
            )

        change_bytes = _canonical_json([item.as_dict() for item in normalized])
        change_digest = _sha256(change_bytes)
        review_digest = _sha256(diff_bytes)
        final_dir = self.root / return_id
        if final_dir.exists():
            raise ProviderArtifactError("ADOPTION_ARTIFACT_ALREADY_EXISTS")
        temp_dir = self.root / f".{return_id}.tmp-{uuid.uuid4().hex}"

        entries = [("change-set.json", change_bytes), ("review.diff", diff_bytes), *payloads]
        try:
            temp_dir.mkdir(parents=False, exist_ok=False)
            for name, data in entries:
                _write_bytes(temp_dir / name, data)
            _write_bytes(temp_dir / "manifest.sha256", _manifest_bytes(entries))
            temp_dir.rename(final_dir)
        except Exception:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise

        return StoredProviderArtifact(
            return_id=return_id,
            change_set_digest=change_digest,
            review_diff_digest=review_digest,
            changed_file_count=len(normalized),
            payload_bytes=payload_bytes,
            changes=tuple(normalized),
            review_diff=review_diff,
        )

    def load(
        self,
        return_id: str,
        *,
        expected_change_set_digest: str | None = None,
    ) -> StoredProviderArtifact:
        """重新验证 manifest、payload 和 change-set 后返回 Artifact。"""

        if not _RETURN_ID.fullmatch(return_id):
            raise ProviderArtifactError("ADOPTION_ARTIFACT_INVALID")
        artifact_dir = self.root / return_id
        try:
            manifest_text = (artifact_dir / "manifest.sha256").read_text("utf-8")
            manifest: dict[str, str] = {}
            for line in manifest_text.splitlines():
                digest, name = line.split("  ", 1)
                if not _SHA256.fullmatch(digest) or name.startswith("/") or ".." in name.split("/"):
                    raise ProviderArtifactError("ADOPTION_ARTIFACT_INVALID")
                manifest[name] = digest
            if "change-set.json" not in manifest or "review.diff" not in manifest:
                raise ProviderArtifactError("ADOPTION_ARTIFACT_INVALID")
            for name, expected in manifest.items():
                data = (artifact_dir / name).read_bytes()
                if _sha256(data) != expected:
                    raise ProviderArtifactError("ADOPTION_ARTIFACT_INVALID")

            change_bytes = (artifact_dir / "change-set.json").read_bytes()
            change_digest = _sha256(change_bytes)
            if (
                expected_change_set_digest is not None
                and change_digest != expected_change_set_digest
            ):
                raise ProviderArtifactError("ADOPTION_ARTIFACT_INVALID")
            raw_changes = json.loads(change_bytes.decode("utf-8"))
            if not isinstance(raw_changes, list) or len(raw_changes) > MAX_CHANGED_FILES:
                raise ProviderArtifactError("ADOPTION_ARTIFACT_INVALID")

            changes: list[NormalizedChange] = []
            payload_bytes = 0
            for raw in raw_changes:
                if not isinstance(raw, dict) or set(raw) != {
                    "operation",
                    "path",
                    "base_sha256",
                    "result_sha256",
                    "size_bytes",
                    "payload_name",
                }:
                    raise ProviderArtifactError("ADOPTION_ARTIFACT_INVALID")
                safe_path = _safe_relative_path(str(raw["path"]))
                operation = raw["operation"]
                if operation not in {"add", "modify", "delete"}:
                    raise ProviderArtifactError("ADOPTION_ARTIFACT_INVALID")
                base_sha = raw["base_sha256"]
                result_sha = raw["result_sha256"]
                size_bytes = raw["size_bytes"]
                payload_name = raw["payload_name"]
                if not isinstance(size_bytes, int) or size_bytes < 0:
                    raise ProviderArtifactError("ADOPTION_ARTIFACT_INVALID")

                if operation == "delete":
                    if not isinstance(base_sha, str) or not _SHA256.fullmatch(base_sha):
                        raise ProviderArtifactError("ADOPTION_ARTIFACT_INVALID")
                    if result_sha is not None or payload_name is not None or size_bytes != 0:
                        raise ProviderArtifactError("ADOPTION_ARTIFACT_INVALID")
                else:
                    if operation == "add" and base_sha is not None:
                        raise ProviderArtifactError("ADOPTION_ARTIFACT_INVALID")
                    if operation == "modify" and (
                        not isinstance(base_sha, str) or not _SHA256.fullmatch(base_sha)
                    ):
                        raise ProviderArtifactError("ADOPTION_ARTIFACT_INVALID")
                    if not isinstance(result_sha, str) or not _SHA256.fullmatch(result_sha):
                        raise ProviderArtifactError("ADOPTION_ARTIFACT_INVALID")
                    if not isinstance(payload_name, str) or not payload_name.startswith("payload/"):
                        raise ProviderArtifactError("ADOPTION_ARTIFACT_INVALID")
                    payload = (artifact_dir / payload_name).read_bytes()
                    if len(payload) != size_bytes or len(payload) > MAX_FILE_BYTES:
                        raise ProviderArtifactError("ADOPTION_ARTIFACT_INVALID")
                    if _sha256(payload) != result_sha:
                        raise ProviderArtifactError("ADOPTION_ARTIFACT_INVALID")
                    text = payload.decode("utf-8")
                    _reject_secret(text)
                    payload_bytes += len(payload)
                    if payload_bytes > MAX_PAYLOAD_BYTES:
                        raise ProviderArtifactError("ADOPTION_ARTIFACT_INVALID")

                changes.append(
                    NormalizedChange(
                        operation=operation,
                        path=safe_path,
                        base_sha256=base_sha,
                        result_sha256=result_sha,
                        size_bytes=size_bytes,
                        payload_name=payload_name,
                    )
                )

            review_bytes = (artifact_dir / "review.diff").read_bytes()
            if len(review_bytes) > MAX_REVIEW_DIFF_BYTES:
                raise ProviderArtifactError("ADOPTION_ARTIFACT_INVALID")
            review_diff = review_bytes.decode("utf-8")
            _reject_secret(review_diff)
            return StoredProviderArtifact(
                return_id=return_id,
                change_set_digest=change_digest,
                review_diff_digest=_sha256(review_bytes),
                changed_file_count=len(changes),
                payload_bytes=payload_bytes,
                changes=tuple(changes),
                review_diff=review_diff,
            )
        except ProviderArtifactError:
            raise
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            raise ProviderArtifactError("ADOPTION_ARTIFACT_INVALID") from exc
