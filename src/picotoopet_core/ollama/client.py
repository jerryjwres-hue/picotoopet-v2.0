"""Ollama HTTP API 的最小客户端。"""

from __future__ import annotations

import httpx


class OllamaClient:
    """封装模型清单、运行状态和常驻预加载。"""

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
