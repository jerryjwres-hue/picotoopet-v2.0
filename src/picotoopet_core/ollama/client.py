"""Ollama HTTP API 的最小客户端。"""

from __future__ import annotations

from datetime import datetime

import httpx
from pydantic import BaseModel, ConfigDict, Field


_MAX_OBSERVED_MODELS = 32


class OllamaVersionObservation(BaseModel):
    """只包含诊断需要的非敏感 Ollama 版本事实。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1, max_length=64)


class OllamaLoadedModelObservation(BaseModel):
    """运行中模型的安全子集；刻意排除 digest、路径和任意 details。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=128)
    size_bytes: int | None = Field(default=None, ge=0, le=10**15)
    vram_bytes: int | None = Field(default=None, ge=0, le=10**15)
    expires_at: datetime | None = None


class OllamaProcessSnapshot(BaseModel):
    """`/api/ps` 的有界只读投影。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    loaded_model_count: int = Field(ge=0, le=100_000)
    models: tuple[OllamaLoadedModelObservation, ...] = Field(max_length=_MAX_OBSERVED_MODELS)
    truncated: bool = False


class OllamaClient:
    """封装模型清单、运行状态、只读诊断观察和常驻预加载。"""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self._owns_client = client is None
        self.client       = client or httpx.Client(base_url=base_url, timeout=timeout_seconds)

    def close(self) -> None:
        """关闭由本实例创建的连接池。"""

        if self._owns_client:
            self.client.close()

    def installed_models(self) -> set[str]:
        """读取已安装模型名称。"""

        response = self.client.get("/api/tags")
        response.raise_for_status()
        return {str(item["name"]) for item in response.json().get("models", [])}

    def running_models(self) -> set[str]:
        """读取当前已加载模型名称。"""

        response = self.client.get("/api/ps")
        response.raise_for_status()
        return {str(item["name"]) for item in response.json().get("models", [])}

    def version_info(self) -> OllamaVersionObservation:
        """只读观察 `/api/version`；不执行加载、卸载或模型下载。"""

        response = self.client.get("/api/version")
        response.raise_for_status()
        payload  = response.json()
        version  = str(payload.get("version", "")).strip()
        return OllamaVersionObservation(version=version)

    def process_snapshot(self) -> OllamaProcessSnapshot:
        """只读观察 `/api/ps` 并只保留可靠性诊断允许的安全字段。"""

        response   = self.client.get("/api/ps")
        response.raise_for_status()
        payload    = response.json()
        raw_models = payload.get("models", [])
        if not isinstance(raw_models, list):
            raw_models = []

        observations: list[OllamaLoadedModelObservation] = []
        for item in raw_models[:_MAX_OBSERVED_MODELS]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("model") or "").strip()
            if not name:
                continue
            observations.append(
                OllamaLoadedModelObservation(
                    name=name[:128],
                    size_bytes=_bounded_nonnegative_int(item.get("size")),
                    vram_bytes=_bounded_nonnegative_int(item.get("size_vram")),
                    expires_at=_bounded_datetime(item.get("expires_at")),
                )
            )

        return OllamaProcessSnapshot(
            loaded_model_count=min(len(raw_models), 100_000),
            models=tuple(observations),
            truncated=len(raw_models) > _MAX_OBSERVED_MODELS,
        )

    def preload(self, model_name: str) -> None:
        """以负 keep_alive 预加载模型，要求 Ollama 永久保留。"""

        response = self.client.post(
            "/api/generate",
            json={
                "model": model_name,
                "prompt": "",
                "stream": False,
                "keep_alive": -1,
            },
        )
        response.raise_for_status()


def _bounded_nonnegative_int(value: object) -> int | None:
    """只接受 Ollama 返回的非负整数；异常字段不进入诊断快照。"""

    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return min(max(value, 0), 10**15)


def _bounded_datetime(value: object) -> datetime | None:
    """把 ISO 时间转换为结构化值；无效时间不携带原始字符串。"""

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
