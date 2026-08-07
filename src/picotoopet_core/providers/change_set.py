"""Provider Return 的有界、可重放文本变更描述。"""

from dataclasses import dataclass
from typing import Literal


ChangeOperation = Literal["add", "modify", "delete"]


@dataclass(frozen=True, slots=True)
class ProviderChangeInput:
    """Artifact Store 写入前的内存输入；正文不会进入 SQLite。"""

    operation: ChangeOperation
    path: str
    base_sha256: str | None = None
    result_text: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizedChange:
    """持久化到 change-set.json 的无正文变更元数据。"""

    operation: ChangeOperation
    path: str
    base_sha256: str | None
    result_sha256: str | None
    size_bytes: int
    payload_name: str | None

    def as_dict(self) -> dict[str, object]:
        """返回稳定 JSON 字段映射。"""

        return {
            "operation": self.operation,
            "path": self.path,
            "base_sha256": self.base_sha256,
            "result_sha256": self.result_sha256,
            "size_bytes": self.size_bytes,
            "payload_name": self.payload_name,
        }
