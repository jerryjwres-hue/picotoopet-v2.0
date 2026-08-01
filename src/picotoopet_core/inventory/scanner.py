"""不修改源文件的确定性盘点器。"""

from __future__ import annotations

import hashlib
import os
import platform
from pathlib import Path

from pydantic import BaseModel, Field

_SECRET_MARKERS = ("token", "secret", "password", "api_key", "apikey", "credential")


class InventoryFile(BaseModel):
    """单个只读文件记录。"""

    relative_path: str
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class FileInventory(BaseModel):
    """目录盘点结果；不包含绝对 Protected 路径内容。"""

    root_name: str
    file_count: int = Field(ge=0)
    total_bytes: int = Field(ge=0)
    files: list[InventoryFile]


class InventoryScanner:
    """以只读方式计算清单和环境状态。"""

    def scan_tree(self, root: Path | str) -> FileInventory:
        """递归读取普通文件并按相对路径排序。"""

        root_path = Path(root).expanduser().resolve(strict=True)
        records: list[InventoryFile] = []
        for path in sorted(
            (item for item in root_path.rglob("*") if item.is_file()),
            key=lambda item: item.relative_to(root_path).as_posix(),
        ):
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            records.append(
                InventoryFile(
                    relative_path=path.relative_to(root_path).as_posix(),
                    size_bytes=path.stat().st_size,
                    sha256=digest.hexdigest(),
                )
            )
        return FileInventory(
            root_name=root_path.name,
            file_count=len(records),
            total_bytes=sum(item.size_bytes for item in records),
            files=records,
        )

    def scan_environment(self, *, names: list[str]) -> dict[str, str | None]:
        """只记录普通变量值；敏感变量仅记录存在状态。"""

        inventory: dict[str, str | None] = {}
        for name in names:
            value = os.environ.get(name)
            if value is None:
                inventory[name] = None
            elif any(marker in name.lower() for marker in _SECRET_MARKERS):
                inventory[name] = "***PRESENT_REDACTED***"
            else:
                inventory[name] = value
        return inventory

    def platform_inventory(self) -> dict[str, str]:
        """返回不含用户名和凭证的基础运行环境。"""

        return {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        }
