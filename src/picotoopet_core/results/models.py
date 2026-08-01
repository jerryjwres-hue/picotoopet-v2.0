"""结果存储返回模型。"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StoredResult:
    object_hash: str
    object_path: Path
    manifest_path: Path
    size_bytes: int
    result_type: str
