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

    @property
    def provider_returns_dir(self) -> Path:
        """返回仅由 Mac Core 推导的 Provider Return Artifact 根目录。"""

        return self.runtime_dir / "provider-returns"

    @property
    def business_root(self) -> Path:
        """业务自动化只使用 Mac Core 自主管理的运行目录。"""

        return self.runtime_dir / "business"

    @property
    def business_staging_dir(self) -> Path:
        return self.business_root / "staging"

    @property
    def business_packages_dir(self) -> Path:
        return self.business_root / "packages"

    @property
    def business_results_dir(self) -> Path:
        return self.business_root / "results"

    @property
    def business_handoffs_dir(self) -> Path:
        return self.business_root / "handoffs"

    @property
    def creative_root(self) -> Path:
        """Creative Intelligence 只使用 Mac Core 自主管理的运行目录。"""

        return self.runtime_dir / "creative"

    @property
    def creative_packages_dir(self) -> Path:
        return self.creative_root / "packages"

    @property
    def creative_handoffs_dir(self) -> Path:
        return self.creative_root / "handoffs"

    @property
    def production_root(self) -> Path:
        """Production 只保存 Core 管理的结果清单，不接管 ComfyUI 数据根。"""

        return self.runtime_dir / "production"

    @property
    def production_packages_dir(self) -> Path:
        return self.production_root / "packages"

    @property
    def deep_ai_root(self) -> Path:
        """付费 AI 升级仅使用 Mac Core 自主管理的脱敏包/结果目录。"""

        return self.runtime_dir / "deep-ai"

    @property
    def deep_ai_requests_dir(self) -> Path:
        return self.deep_ai_root / "requests"

    @property
    def deep_ai_results_dir(self) -> Path:
        return self.deep_ai_root / "results"

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
            self.provider_returns_dir,
            self.business_root,
            self.business_staging_dir,
            self.business_packages_dir,
            self.business_results_dir,
            self.business_handoffs_dir,
            self.creative_root,
            self.creative_packages_dir,
            self.creative_handoffs_dir,
            self.production_root,
            self.production_packages_dir,
            self.deep_ai_root,
            self.deep_ai_requests_dir,
            self.deep_ai_results_dir,
        )

    def ensure(self) -> None:
        """只创建 V2 受控目录。"""

        for directory in self.managed_directories():
            directory.mkdir(parents=True, exist_ok=True)
