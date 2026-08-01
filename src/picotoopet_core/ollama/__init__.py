"""Ollama 本地主模型常驻管理。"""

from .client import OllamaClient
from .resident_manager import ResidentManager, ResidentResult, ResidentStatus

__all__ = ["OllamaClient", "ResidentManager", "ResidentResult", "ResidentStatus"]
