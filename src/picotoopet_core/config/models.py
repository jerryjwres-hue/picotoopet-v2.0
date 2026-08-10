"""应用配置模型。"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .paths import RuntimePaths


class AppSettings(BaseModel):
    """Mac Core 的不可变运行配置。"""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    paths: RuntimePaths
    api_token: str = Field(min_length=16)
    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8765, ge=1, le=65535)
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "gpt-oss:20b"
    local_intelligence_base_url: str = "http://127.0.0.1:11434/v1/"
    local_intelligence_model: str = "gpt-oss:20b"
    local_intelligence_timeout_seconds: float = Field(default=900.0, ge=1.0, le=3600.0)
    local_intelligence_max_context_chars: int = Field(default=240_000, ge=10_000, le=1_000_000)
    resident_check_seconds: int = Field(default=60, ge=10)
    protected_roots: tuple[str, ...] = ()
    worker_poll_seconds: float = Field(default=2.0, gt=0, le=60)
    worker_lease_seconds: int = Field(default=60, ge=2, le=3600)
    worker_heartbeat_seconds: int = Field(default=15, ge=1, le=1800)
    worker_status_stale_seconds: int = Field(default=45, ge=2, le=7200)
    workflow_reconcile_seconds: float = Field(default=1.0, ge=0.05, le=60.0)
    provider_repository: Path | None = None
    provider_worktree_root: Path | None = None
    codex_executable: Path | None = None
    github_cli_executable: Path | None = None

    @property
    def provider_execution_configured(self) -> bool:
        return all(
            value is not None
            for value in (
                self.provider_repository,
                self.provider_worktree_root,
                self.codex_executable,
            )
        )

    @property
    def provider_publication_configured(self) -> bool:
        """远端 publication 只依赖本地 Provider 仓库和固定 GitHub CLI。"""

        return self.provider_repository is not None and self.github_cli_executable is not None

    def redacted_dict(self) -> dict[str, object]:
        """返回可安全写入日志的配置副本。"""

        payload = self.model_dump(mode="python")
        payload["paths"] = {"root": str(self.paths.root)}
        payload["api_token"] = "***REDACTED***"
        payload["provider_repository"] = (
            "configured" if self.provider_repository is not None else "disabled"
        )
        payload["provider_worktree_root"] = (
            "configured" if self.provider_worktree_root is not None else "disabled"
        )
        payload["codex_executable"] = (
            "configured" if self.codex_executable is not None else "disabled"
        )
        payload["github_cli_executable"] = (
            "configured" if self.github_cli_executable is not None else "disabled"
        )
        payload["local_intelligence_base_url"] = "loopback-configured"
        payload["local_intelligence_model"] = self.local_intelligence_model
        return payload
