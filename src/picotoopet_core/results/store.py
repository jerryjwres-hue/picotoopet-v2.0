"""原子、内容寻址的 Result Store。"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from .integrity import sha256_file
from .models import StoredResult


class ResultStore:
    """只在自身根目录创建对象和清单。"""

    def __init__(self, root: Path | str) -> None:
        self.root          = Path(root).expanduser().resolve()
        self.objects_dir   = self.root / "objects"
        self.manifests_dir = self.root / "manifests"
        self.objects_dir.mkdir(parents=True, exist_ok=True)
        self.manifests_dir.mkdir(parents=True, exist_ok=True)

    def _object_path(self, object_hash: str) -> Path:
        return self.objects_dir / object_hash[:2] / object_hash[2:]

    def _write_atomic(self, destination: Path, data: bytes) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            return
        descriptor, temporary_name = tempfile.mkstemp(prefix=".partial-", dir=destination.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def put_bytes(self, data: bytes, *, result_type: str) -> StoredResult:
        """存储字节并写入不可变清单。"""

        object_hash = hashlib.sha256(data).hexdigest()
        object_path = self._object_path(object_hash)
        self._write_atomic(object_path, data)

        manifest_path = self.manifests_dir / f"{object_hash}.json"
        manifest = {
            "object_hash": object_hash,
            "size_bytes": len(data),
            "result_type": result_type,
            "created_at": datetime.now(UTC).isoformat(),
        }
        if not manifest_path.exists():
            self._write_atomic(
                manifest_path,
                json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8"),
            )
        return StoredResult(object_hash, object_path, manifest_path, len(data), result_type)

    def put_file(self, source: Path | str, *, result_type: str) -> StoredResult:
        """只读打开源文件，将副本写入对象存储。"""

        source_path = Path(source).expanduser().resolve(strict=True)
        with source_path.open("rb") as handle:
            data = handle.read()
        return self.put_bytes(data, result_type=result_type)

    def verify(self, object_hash: str) -> bool:
        """验证对象路径和内容哈希。"""

        object_path = self._object_path(object_hash)
        return object_path.is_file() and sha256_file(object_path) == object_hash
