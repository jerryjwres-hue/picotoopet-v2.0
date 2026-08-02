"""Mac Core 运行目录定义。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    """V2 自主管理的目录集合，不包含任何 Protected 原始路径。"""

    root: Path

    @classmethod
    def from_root(cls, root: Path | str) -> RuntimePaths:
        """从显式根目录构建并标准化路径。"""

        return cls(root=Path(root).expanduser().resolve())

    @property
    def database_dir(self) -> Path:
        return self.root / "database"

    @property
    def database_file(self) -> Path:
        return self.database_dir / "core.db"

    @property
    def results_dir(self) -> Path:
        return self.root / "results"

    @property
    def objects_dir(self) -> Path:
        return self.results_dir / "objects"

    @property
    def manifests_dir(self) -> Path:
        return self.results_dir / "manifests"

    @property
    def audit_dir(self) -> Path:
        return self.root / "audit"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def state_dir(self) -> Path:
        return self.root / "state"

    @property
    def pairing_dir(self) -> Path:
        return self.root / "pairing"

    @property
    def backups_dir(self) -> Path:
        return self.root / "backups"

    @property
    def runtime_dir(self) -> Path:
        return self.root / "runtime"

    def managed_directories(self) -> tuple[Path, ...]:
        """返回安装器和运行时允许创建的全部目录。"""

        return (
            self.root,
            self.database_dir,
            self.results_dir,
            self.objects_dir,
            self.manifests_dir,
            self.audit_dir,
            self.logs_dir,
            self.state_dir,
            self.pairing_dir,
            self.backups_dir,
            self.runtime_dir,
        )

    def ensure(self) -> None:
        """只创建 V2 受控目录。"""

        for directory in self.managed_directories():
            directory.mkdir(parents=True, exist_ok=True)
