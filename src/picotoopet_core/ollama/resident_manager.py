"""gpt-oss:20b 常驻状态机。"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from .client import OllamaClient


class ResidentStatus(StrEnum):
    """常驻管理检查结果。"""

    RESIDENT      = "resident"
    MODEL_MISSING = "model_missing"
    ERROR         = "error"


class ResidentResult(BaseModel):
    """常驻检查的结构化结果。"""

    status: ResidentStatus
    model_name: str
    detail: str


class ResidentManager:
    """检查并恢复唯一核心模型的常驻状态。"""

    def __init__(self, client: OllamaClient, model_name: str = "gpt-oss:20b") -> None:
        self.client     = client
        self.model_name = model_name

    def ensure_resident(self) -> ResidentResult:
        """缺失时只报告；已安装时确保模型被加载并保持常驻。"""

        try:
            installed = self.client.installed_models()
            if self.model_name not in installed:
                return ResidentResult(
                    status=ResidentStatus.MODEL_MISSING,
                    model_name=self.model_name,
                    detail="模型尚未安装；常驻管理器不会擅自下载大模型。",
                )

            if self.model_name not in self.client.running_models():
                self.client.preload(self.model_name)

            if self.model_name not in self.client.running_models():
                return ResidentResult(
                    status=ResidentStatus.ERROR,
                    model_name=self.model_name,
                    detail="预加载请求完成，但模型未出现在运行清单。",
                )

            return ResidentResult(
                status=ResidentStatus.RESIDENT,
                model_name=self.model_name,
                detail="核心模型已常驻。",
            )
        except Exception as exc:  # noqa: BLE001 - 转换为健康状态，不泄漏到守护进程
            return ResidentResult(
                status=ResidentStatus.ERROR,
                model_name=self.model_name,
                detail=f"Ollama 常驻检查失败：{type(exc).__name__}",
            )
