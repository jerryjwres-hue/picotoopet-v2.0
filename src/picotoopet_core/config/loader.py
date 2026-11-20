"""从环境变量加载应用配置。"""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

from picotoopet_core.security.owner_registry_loader import load_owner_review_registry

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
        # 仅本机管理员的 0600 文件可提供 Owner 权限；缺失则默认关闭。
        owner_review_registry=load_owner_review_registry(Path(runtime_root).expanduser()),
        api_host=os.getenv("PICOTOO_API_HOST", "0.0.0.0"),
        api_port=int(os.getenv("PICOTOO_API_PORT", "8765")),
        ollama_base_url=os.getenv("PICOTOO_OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        ollama_model=os.getenv("PICOTOO_OLLAMA_MODEL", "gpt-oss:20b"),
        resident_check_seconds=int(os.getenv("PICOTOO_RESIDENT_CHECK_SECONDS", "60")),
        protected_roots=protected,
        mobile_studio_enabled=os.getenv("PICOTOO_MOBILE_STUDIO_ENABLED", "0") == "1",
        episode_max_takes_per_shot=int(os.getenv("PICOTOO_EPISODE_MAX_TAKES_PER_SHOT", "8")),
        episode_max_takes_per_episode=int(os.getenv("PICOTOO_EPISODE_MAX_TAKES_PER_EPISODE", "48")),
        episode_max_reserved_video_seconds=float(
            os.getenv("PICOTOO_EPISODE_MAX_RESERVED_VIDEO_SECONDS", "2160")
        ),
    )
