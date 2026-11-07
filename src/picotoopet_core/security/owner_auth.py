"""Narrow FastAPI dependency for owner-fact reviews only.

Do not mount this dependency on the existing device-authenticated API router.
Remote owner-review access remains disabled until a verified encrypted transport is deployed.
"""

from __future__ import annotations

from ipaddress import ip_address

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from picotoopet_core.api.errors import ApiError

from .owner_principal import (
    OwnerAuthFailure,
    OwnerPrincipal,
    require_owner_actor,
    require_owner_scope,
    resolve_owner_principal,
)

_owner_bearer = HTTPBearer(auto_error=False)
_UNTRUSTED_PROXY_HEADERS = ("forwarded", "x-forwarded-for", "x-forwarded-proto", "x-real-ip")


def _require_local_direct_peer(request: Request) -> None:
    """Fail closed: forwarded client metadata can never prove a secure channel."""

    client = request.scope.get("client")
    address = client[0] if isinstance(client, tuple) and client else None
    try:
        is_loopback = isinstance(address, str) and ip_address(address).is_loopback
    except ValueError:
        is_loopback = False
    if not is_loopback or any(name in request.headers for name in _UNTRUSTED_PROXY_HEADERS):
        raise ApiError(
            status_code=403,
            code="OWNER_REVIEW_ENCRYPTED_TRANSPORT_REQUIRED",
            message="主人审核需要经过核实的本机连接或加密传输。",
            retryable=False,
        )


def require_owner_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_owner_bearer),
) -> OwnerPrincipal:
    """Resolve scoped actor from operator-managed credentials; no body/header identity."""

    _require_local_direct_peer(request)
    supplied = (
        credentials.credentials
        if credentials is not None and credentials.scheme.casefold() == "bearer"
        else None
    )
    settings = request.app.state.services.settings
    try:
        return resolve_owner_principal(
            supplied_token=supplied,
            device_token=settings.api_token,
            registry=settings.owner_review_registry,
        )
    except OwnerAuthFailure as error:
        raise ApiError(
            status_code=error.status_code,
            code=error.code,
            message="主人审核认证或权限校验失败。",
            retryable=False,
        ) from error


def authorize_owner_subject(principal: OwnerPrincipal, subject_key: str) -> None:
    """Use only Core-derived grants; subject identity in a request is never authority."""

    try:
        require_owner_scope(principal, subject_key)
    except OwnerAuthFailure as error:
        raise ApiError(
            status_code=error.status_code,
            code=error.code,
            message="该审核凭据没有此宠物主体的审核权限。",
            retryable=False,
        ) from error


def authorize_review_actor(principal: OwnerPrincipal, actor_id: str) -> None:
    """A resumed review from a different actor must not inherit the original approval."""

    try:
        require_owner_actor(principal, actor_id)
    except OwnerAuthFailure as error:
        raise ApiError(
            status_code=error.status_code,
            code=error.code,
            message="当前审核人不匹配已冻结的审核身份。",
            retryable=False,
        ) from error
