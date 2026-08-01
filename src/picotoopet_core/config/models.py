"""应用配置模型。"""

from __future__ import annotations

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
    resident_check_seconds: int = Field(default=60, ge=10)
    protected_roots: tuple[str, ...] = ()

    def redacted_dict(self) -> dict[str, object]:
        """返回可安全写入日志的配置副本。"""

        payload = self.model_dump(mode="python")
        payload["paths"] = {"root": str(self.paths.root)}
        payload["api_token"] = "***REDACTED***"
        return payload
