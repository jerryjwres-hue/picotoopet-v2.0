"""从环境变量加载应用配置。"""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

from .keychain import read_api_token_from_keychain
from .models import AppSettings
from .paths import RuntimePaths


def _default_runtime_root() -> Path:
    """根据平台选择本机应用数据目录。"""

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "PicotooPetV2"
    return Path.home() / ".local" / "share" / "PicotooPetV2"


def load_settings() -> AppSettings:
    """加载配置；未提供令牌时生成本次安装使用的随机令牌。"""

    runtime_root = os.getenv("PICOTOO_RUNTIME_ROOT", str(_default_runtime_root()))
    api_token = (
        os.getenv("PICOTOO_API_TOKEN")
        or read_api_token_from_keychain()
        or secrets.token_urlsafe(32)
    )
    protected = tuple(
        item.strip()
        for item in os.getenv("PICOTOO_PROTECTED_ROOTS", "").split(os.pathsep)
        if item.strip()
    )

    return AppSettings(
        paths=RuntimePaths.from_root(runtime_root),
        api_token=api_token,
        api_host=os.getenv("PICOTOO_API_HOST", "0.0.0.0"),
        api_port=int(os.getenv("PICOTOO_API_PORT", "8765")),
        ollama_base_url=os.getenv("PICOTOO_OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        ollama_model=os.getenv("PICOTOO_OLLAMA_MODEL", "gpt-oss:20b"),
        resident_check_seconds=int(os.getenv("PICOTOO_RESIDENT_CHECK_SECONDS", "60")),
        protected_roots=protected,
        worker_poll_seconds=float(os.getenv("PICOTOO_WORKER_POLL_SECONDS", "2")),
        worker_lease_seconds=int(os.getenv("PICOTOO_WORKER_LEASE_SECONDS", "60")),
        worker_heartbeat_seconds=int(os.getenv("PICOTOO_WORKER_HEARTBEAT_SECONDS", "15")),
        worker_status_stale_seconds=int(
            os.getenv("PICOTOO_WORKER_STATUS_STALE_SECONDS", "45")
        ),
    )
