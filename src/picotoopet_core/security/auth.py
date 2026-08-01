"""局域网 REST API Bearer 认证。"""

from __future__ import annotations

import hmac

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from picotoopet_core.api.errors import ApiError

_bearer = HTTPBearer(auto_error=False)


def require_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """使用常量时间比较认证，不回显提交的秘密。"""

    expected = request.app.state.services.settings.api_token
    supplied = "" if credentials is None else credentials.credentials
    if credentials is None or credentials.scheme.lower() != "bearer" or not hmac.compare_digest(
        supplied,
        expected,
    ):
        raise ApiError(
            status_code=401,
            code="AUTHENTICATION_REQUIRED",
            message="需要有效的设备令牌。",
            retryable=False,
        )
    return "authenticated-device"
