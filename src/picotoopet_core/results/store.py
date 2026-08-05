"""原子、内容寻址的 Result Store。"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .integrity import sha256_file
from .models import StoredResult


class ResultTooLargeError(ValueError):
    """结果序列化后超过调用方冻结的大小上限。"""


class ResultStore:
    """只在自身根目录创建对象和清单。"""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser().resolve()
        self.objects_dir = self.root / "objects"
        self.manifests_dir = self.root / "manifests"
        self.objects_dir.mkdir(parents=True, exist_ok=True)
        self.manifests_dir.mkdir(parents=True, exist_ok=True)

    def _object_path(self, object_hash: str) -> Path:
        return self.objects_dir / object_hash[:2] / object_hash[2:]

    def _write_atomic(
        self,
        destination: Path,
        data: bytes,
        *,
        replace_existing: bool = False,
    ) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and not replace_existing:
            return
        if destination.exists() and not destination.is_file():
            raise ValueError(f"结果存储目标不是普通文件：{destination}")

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".partial-",
            dir=destination.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _object_is_valid(
        path: Path,
        *,
        object_hash: str,
        size_bytes: int,
    ) -> bool:
        try:
            return (
                path.is_file()
                and path.stat().st_size == size_bytes
                and sha256_file(path) == object_hash
            )
        except OSError:
            return False

    @staticmethod
    def _manifest_is_valid(
        path: Path,
        *,
        object_hash: str,
        size_bytes: int,
    ) -> bool:
        """对象清单按哈希共享；结果类型由数据库结果记录持有。"""

        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return False
        return (
            isinstance(document, dict)
            and document.get("object_hash") == object_hash
            and document.get("size_bytes") == size_bytes
            and isinstance(document.get("created_at"), str)
            and bool(document["created_at"])
        )

    def put_bytes(self, data: bytes, *, result_type: str) -> StoredResult:
        """存储字节并写入不可变清单；损坏同哈希对象会被原子修复。"""

        object_hash = hashlib.sha256(data).hexdigest()
        object_path = self._object_path(object_hash)
        object_exists = object_path.exists()
        object_valid = self._object_is_valid(
            object_path,
            object_hash=object_hash,
            size_bytes=len(data),
        )
        self._write_atomic(
            object_path,
            data,
            replace_existing=object_exists and not object_valid,
        )
        if not self._object_is_valid(
            object_path,
            object_hash=object_hash,
            size_bytes=len(data),
        ):
            raise ValueError("结果对象写入后的 SHA-256 或大小校验失败。")

        manifest_path = self.manifests_dir / f"{object_hash}.json"
        manifest = {
            "object_hash": object_hash,
            "size_bytes": len(data),
            "result_type": result_type,
            "created_at": datetime.now(UTC).isoformat(),
        }
        manifest_data = json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ).encode("utf-8")
        manifest_exists = manifest_path.exists()
        manifest_valid = self._manifest_is_valid(
            manifest_path,
            object_hash=object_hash,
            size_bytes=len(data),
        )
        self._write_atomic(
            manifest_path,
            manifest_data,
            replace_existing=manifest_exists and not manifest_valid,
        )
        if not self._manifest_is_valid(
            manifest_path,
            object_hash=object_hash,
            size_bytes=len(data),
        ):
            raise ValueError("结果清单写入后校验失败。")

        return StoredResult(
            object_hash,
            object_path,
            manifest_path,
            len(data),
            result_type,
        )

    def put_json(
        self,
        document: Mapping[str, Any],
        *,
        result_type: str,
        max_bytes: int,
    ) -> StoredResult:
        """规范化并有界写入 JSON 对象。"""

        if max_bytes < 1:
            raise ValueError("max_bytes 必须大于 0。")
        data = json.dumps(
            dict(document),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(data) > max_bytes:
            raise ResultTooLargeError(
                f"结果大小 {len(data)} 字节超过上限 {max_bytes} 字节。"
            )
        return self.put_bytes(data, result_type=result_type)

    def put_file(self, source: Path | str, *, result_type: str) -> StoredResult:
        """只读打开源文件，将副本写入对象存储。"""

        source_path = Path(source).expanduser().resolve(strict=True)
        with source_path.open("rb") as handle:
            data = handle.read()
        return self.put_bytes(data, result_type=result_type)

    def read_json(self, object_hash: str, *, max_bytes: int) -> dict[str, Any]:
        """按内容哈希读取并验证有界 JSON，不暴露底层路径。"""

        if max_bytes < 1:
            raise ValueError("max_bytes 必须大于 0。")
        if len(object_hash) != 64 or any(
            character not in "0123456789abcdef" for character in object_hash
        ):
            raise ValueError("object_hash 不是有效的小写 SHA-256。")

        object_path = self._object_path(object_hash)
        if not object_path.is_file():
            raise KeyError(f"结果对象不存在：{object_hash}")
        size_bytes = object_path.stat().st_size
        if size_bytes > max_bytes:
            raise ResultTooLargeError(
                f"结果大小 {size_bytes} 字节超过上限 {max_bytes} 字节。"
            )
        if sha256_file(object_path) != object_hash:
            raise ValueError("结果对象 SHA-256 校验失败。")

        data = object_path.read_bytes()
        try:
            document = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("结果对象不是有效 UTF-8 JSON。") from error
        if not isinstance(document, dict):
            raise ValueError("结果 JSON 顶层必须是对象。")
        return document

    def verify(self, object_hash: str) -> bool:
        """验证对象路径和内容哈希。"""

        object_path = self._object_path(object_hash)
        return object_path.is_file() and sha256_file(object_path) == object_hash
