"""应用配置模型。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from picotoopet_core.security.owner_principal import OwnerReviewRegistry

from .paths import RuntimePaths


class AppSettings(BaseModel):
    """Mac Core 的不可变运行配置。"""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    paths: RuntimePaths
    api_token: str = Field(min_length=16)
    owner_review_registry: OwnerReviewRegistry = Field(default_factory=OwnerReviewRegistry)
    # 可选的一次配置：Worker 额外密钥不等于 Studio/Owner Bearer，也不授予 GPU。
    worker_attestation_id: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9_-]{1,100}$",
    )
    worker_attestation_key: str | None = Field(
        default=None, min_length=43, max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8765, ge=1, le=65535)
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "gpt-oss:20b"
    resident_check_seconds: int = Field(default=60, ge=10)
    protected_roots: tuple[str, ...] = ()
    mobile_studio_enabled: bool = False      # 默认锁定，必须显式开启 HTTPS 手机入口。
    episode_max_takes_per_shot: int = Field(default=8, ge=1, le=48)
    episode_max_takes_per_episode: int = Field(default=48, ge=1, le=500)
    episode_max_reserved_video_seconds: float = Field(default=2160, gt=0, le=14400)

    @model_validator(mode="after")
    def _worker_proof_pair(self) -> "AppSettings":
        # 禁止只填一半而在生产时静默失去独立 Worker 身份验证。
        if (self.worker_attestation_id is None) != (self.worker_attestation_key is None):
            raise ValueError("WORKER_ATTESTATION_ID_AND_KEY_REQUIRED_TOGETHER")
        return self

    def redacted_dict(self) -> dict[str, object]:
        """返回可安全写入日志的配置副本。"""

        payload = self.model_dump(mode="python")
        payload["paths"] = {"root": str(self.paths.root)}
        payload["api_token"] = "***REDACTED***"
        payload["worker_attestation_key"] = (
            "***REDACTED***" if self.worker_attestation_key is not None else None
        )
        # Never expose Owner credential fingerprints or configured subject grants.
        payload["owner_review_registry"] = {
            "configured": len(self.owner_review_registry.credentials),
            "enabled": sum(item.enabled for item in self.owner_review_registry.credentials),
        }
        return payload
