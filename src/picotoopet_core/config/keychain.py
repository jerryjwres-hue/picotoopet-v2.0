"""macOS Keychain 的只读令牌获取。"""

from __future__ import annotations

import getpass
import subprocess
import sys


def read_api_token_from_keychain(service: str = "PicotooPetV2.API") -> str | None:
    """从当前用户 Keychain 获取 API Token；失败时返回 None。"""

    if sys.platform != "darwin":
        return None
    command = [
        "/usr/bin/security",
        "find-generic-password",
        "-a",
        getpass.getuser(),
        "-s",
        service,
        "-w",
    ]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    token = result.stdout.strip()
    return token or None
