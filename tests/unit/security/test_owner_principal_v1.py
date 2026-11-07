"""Narrow owner-review authentication: no real credentials, owner data or network."""

from __future__ import annotations

import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError
from starlette.requests import Request

from picotoopet_core.api.errors import ApiError
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.owner_registry import load_owner_review_registry
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.security.auth import require_auth
from picotoopet_core.security.owner_auth import (
    authorize_owner_subject,
    authorize_review_actor,
    require_owner_principal,
)
from picotoopet_core.security.owner_principal import (
    OwnerAuthFailure,
    OwnerCredentialConfig,
    OwnerReviewRegistry,
    owner_token_fingerprint,
    require_owner_actor,
    require_owner_scope,
    resolve_owner_principal,
)

_DEVICE_TOKEN = "synthetic-device-token-never-owner"


def _registry(
    token: str,
    *,
    subjects: tuple[str, ...] = ("pet:maotai",),
    permissions: tuple[str, ...] = ("owner_facts.review",),
    enabled: bool = True,
    expires_at: datetime | None = None,
) -> OwnerReviewRegistry:
    # Secret is test-only      : the trusted registry contains its fingerprint, never bytes.
    return OwnerReviewRegistry(
        credentials=(
            OwnerCredentialConfig(
                credential_id="owner-local-one",
                actor_id="owner-local",
                token_sha256=owner_token_fingerprint(token),
                subject_keys=subjects,
                permissions=permissions,
                registry_revision=1,
                enabled=enabled,
                expires_at=expires_at,
            ),
        )
    )


def _request(
    registry: OwnerReviewRegistry,
    *,
    tmp_path: Path,
    client: str = "127.0.0.1",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> Request:
    app = FastAPI()
    app.state.services = SimpleNamespace(
        settings=AppSettings(
            paths=RuntimePaths.from_root(tmp_path),
            api_token=_DEVICE_TOKEN,
            owner_review_registry=registry,
        )
    )
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/owner-review",
            "scheme": "http",
            "headers": headers or [],
            "client": (client, 52137),
            "server": ("127.0.0.1", 8765),
            "app": app,
        }
    )


def _bearer(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def test_owner_principal_scoped_actor_and_legacy_separation(tmp_path: Path) -> None:
    owner_secret = secrets.token_urlsafe(32)
    settings = _registry(owner_secret)
    request = _request(settings, tmp_path=tmp_path)

    # Only the distinct owner token earns actor and per-subject authority.
    principal = require_owner_principal(request, _bearer(owner_secret))
    assert principal.actor_id == "owner-local"
    assert principal.credential_id == "owner-local-one"
    assert principal.subject_keys == ("pet:maotai",)
    authorize_owner_subject(principal, "pet:maotai")
    authorize_review_actor(principal, "owner-local")
    assert require_auth(request, _bearer(_DEVICE_TOKEN)) == "authenticated-device"

    with pytest.raises(ApiError) as owner_on_device:
        require_auth(request, _bearer(owner_secret))
    assert owner_on_device.value.status_code == 401

    with pytest.raises(ApiError) as device_on_owner:
        require_owner_principal(request, _bearer(_DEVICE_TOKEN))
    assert device_on_owner.value.status_code == 403
    assert device_on_owner.value.code == "OWNER_REVIEW_DEVICE_TOKEN_FORBIDDEN"

    with pytest.raises(ApiError) as wrong_subject:
        authorize_owner_subject(principal, "pet:other-dog")
    assert wrong_subject.value.status_code == 403
    with pytest.raises(ApiError) as wrong_actor:
        authorize_review_actor(principal, "owner-other")
    assert wrong_actor.value.status_code == 403


def test_owner_principal_missing_bad_disabled_expired_and_limited_grants(tmp_path: Path) -> None:
    token = secrets.token_urlsafe(32)
    for credential in (None, _bearer(secrets.token_urlsafe(32))):
        with pytest.raises(ApiError) as error:
            require_owner_principal(_request(_registry(token), tmp_path=tmp_path), credential)
        assert error.value.status_code == 401

    for registry in (
        OwnerReviewRegistry(),
        _registry(token, enabled=False),
        _registry(token, expires_at=datetime.now(UTC) - timedelta(days=1)),
    ):
        with pytest.raises(ApiError) as error:
            require_owner_principal(_request(registry, tmp_path=tmp_path), _bearer(token))
        assert error.value.status_code == 401

    principal = resolve_owner_principal(
        supplied_token=token, device_token=_DEVICE_TOKEN,
        registry=_registry(token, permissions=()),
    )
    with pytest.raises(OwnerAuthFailure) as error:
        require_owner_scope(principal, "pet:maotai")
    assert error.value.status_code == 403
    with pytest.raises(OwnerAuthFailure) as error:
        require_owner_actor(principal, "other")
    assert error.value.status_code == 403


def test_rejects_unknown_subject_and_duplicate_credentials() -> None:
    token = secrets.token_urlsafe(32)
    with pytest.raises(ValidationError):
        _registry(token, subjects=("pet:*",))
    with pytest.raises(ValidationError):
        _registry(token, subjects=("pet:maotai", "pet:maotai"))
    grant = _registry(token).credentials[0]
    with pytest.raises(ValidationError):
        OwnerReviewRegistry(credentials=(grant, grant))
    with pytest.raises(ValidationError):
        OwnerCredentialConfig(
            **{**grant.model_dump(), "permissions": ["owner_facts.review", "owner_facts.review"]}
        )


def test_transport_never_trusts_unverified_proxy_or_remote_http(tmp_path: Path) -> None:
    token = secrets.token_urlsafe(32)
    registry = _registry(token)
    for client, headers in (
        ("192.168.68.10", []),
        ("127.0.0.1", [(b"x-forwarded-proto", b"https")]),
        ("127.0.0.1", [(b"x-forwarded-for", b"127.0.0.1")]),
    ):
        with pytest.raises(ApiError) as error:
            require_owner_principal(
                _request(registry, tmp_path=tmp_path, client=client, headers=headers),
                _bearer(token),
            )
        assert error.value.status_code == 403
        assert error.value.code == "OWNER_REVIEW_ENCRYPTED_TRANSPORT_REQUIRED"


def test_redaction_never_exposes_token_fingerprint_or_actor(tmp_path: Path) -> None:
    token = secrets.token_urlsafe(32)
    registry = _registry(token)
    settings = AppSettings(
        paths=RuntimePaths.from_root(tmp_path),
        api_token=_DEVICE_TOKEN,
        owner_review_registry=registry,
    )
    display = str(settings.redacted_dict())
    assert token not in display
    assert owner_token_fingerprint(token) not in display
    assert "owner-local" not in display
    assert settings.redacted_dict()["owner_review_registry"] == {
        "configured": 1,
        "enabled": 1,
    }


def test_protected_registry_needs_file_permissions_and_matching_keychain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = secrets.token_urlsafe(32)
    registry = _registry(token)
    path = tmp_path / "owner-review-registry.json"
    path.write_text(registry.model_dump_json(), encoding="utf-8")
    path.chmod(0o600)
    monkeypatch.setattr(
        "picotoopet_core.config.owner_registry.read_api_token_from_keychain",
        lambda service: token,
    )
    assert load_owner_review_registry(str(path)) == registry

    # Missing Keychain data : no enabled owner permission, even with valid registry bytes.
    monkeypatch.setattr(
        "picotoopet_core.config.owner_registry.read_api_token_from_keychain",
        lambda service: None,
    )
    absent = load_owner_review_registry(str(path))
    assert not absent.credentials[0].enabled

    path.chmod(0o644)
    assert load_owner_review_registry(str(path)).credentials == ()
    path.chmod(0o600)
    symlink = tmp_path / "link.json"
    symlink.symlink_to(path)
    assert load_owner_review_registry(str(symlink)).credentials == ()
    assert load_owner_review_registry(None).credentials == ()
    assert load_owner_review_registry("relative-file.json").credentials == ()


def test_registry_rejects_wrong_secret_and_bad_json(tmp_path: Path, monkeypatch) -> None:
    token = secrets.token_urlsafe(32)
    path = tmp_path / "owner-review-registry.json"
    path.write_text(_registry(token).model_dump_json(), encoding="utf-8")
    path.chmod(0o600)
    monkeypatch.setattr(
        "picotoopet_core.config.owner_registry.read_api_token_from_keychain",
        lambda service: secrets.token_urlsafe(32),
    )
    assert not load_owner_review_registry(str(path)).credentials[0].enabled
    path.write_text("{not-json", encoding="utf-8")
    assert load_owner_review_registry(str(path)).credentials == ()


def test_disabled_owner_configuration_does_not_alter_device_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from picotoopet_core.config.loader import load_settings

    monkeypatch.setenv("PICOTOO_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("PICOTOO_API_TOKEN", _DEVICE_TOKEN)
    monkeypatch.delenv("PICOTOO_OWNER_REVIEW_REGISTRY_FILE", raising=False)
    settings = load_settings()
    assert settings.owner_review_registry.credentials == ()
    assert settings.api_token == _DEVICE_TOKEN
    assert os.path.isabs(str(settings.paths.root))
