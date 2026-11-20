"""OwnerPrincipal remains disabled until a protected local registry is provisioned."""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime, timedelta

import pytest

from picotoopet_core.config.loader import load_settings
from picotoopet_core.security.owner_principal import (
    OwnerReviewRegistry,
    owner_token_fingerprint,
    resolve_owner_principal,
)
from picotoopet_core.security.owner_registry_loader import (
    OwnerRegistryLoadError,
    load_owner_review_registry,
)


def _valid_registry(token: str) -> dict:
    return {
        "schema_version": "owner_review_registry.v1",
        "credentials": [{
            "credential_id": "synthetic-maotai",
            "actor_id": "synthetic-owner",
            "token_sha256": owner_token_fingerprint(token),
            "subject_keys": ["pet:maotai"],
            "permissions": ["storypack.review"],
            "registry_revision": 1,
            "enabled": True,
            "expires_at": (
                datetime.now(UTC) + timedelta(minutes=30)
            ).isoformat(),
        }],
    }


def _write(root, content: str, mode: int = 0o600):
    directory = root / "state"
    directory.mkdir(exist_ok=True)
    path = directory / "owner_review_registry.json"
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)
    return path


def test_missing_owner_registry_disables_approval_without_creating_state(tmp_path):
    assert load_owner_review_registry(tmp_path) == OwnerReviewRegistry()
    assert not (tmp_path / "state").exists()


def test_real_settings_loader_reads_user_owned_registry_but_not_device_token(
    tmp_path, monkeypatch,
):
    token = secrets.token_urlsafe(32)
    device = secrets.token_urlsafe(32)
    _write(tmp_path, json.dumps(_valid_registry(token)))
    monkeypatch.setenv("PICOTOO_RUNTIME_ROOT", str(tmp_path))
    monkeypatch.setenv("PICOTOO_API_TOKEN", device)

    settings = load_settings()
    assert settings.owner_review_registry.credentials[0].enabled is True
    assert settings.redacted_dict()["owner_review_registry"] == {
        "configured": 1, "enabled": 1,
    }
    assert token not in str(settings.redacted_dict())
    assert settings.api_token == device
    principal = resolve_owner_principal(
        supplied_token=token,
        device_token=device,
        registry=settings.owner_review_registry,
    )
    assert principal.actor_id == "synthetic-owner"
    assert principal.permissions == ("storypack.review",)


@pytest.mark.parametrize("problem", [
    "world-readable",
    "group-readable",
    "symlink",
    "duplicate-key",
    "invalid-credential",
    "oversized",
])
def test_bad_local_owner_registry_fails_closed(tmp_path, problem):
    token = secrets.token_urlsafe(32)
    valid = json.dumps(_valid_registry(token))
    path = _write(tmp_path, valid)
    if problem == "world-readable":
        path.chmod(0o644)
    elif problem == "group-readable":
        path.chmod(0o640)
    elif problem == "symlink":
        other = tmp_path / "external.json"
        other.write_text(valid, encoding="utf-8")
        path.unlink()
        path.symlink_to(other)
    elif problem == "duplicate-key":
        path.write_text('{"credentials":[],"credentials":[]}', encoding="utf-8")
    elif problem == "invalid-credential":
        invalid = _valid_registry(token)
        invalid["credentials"][0]["permissions"] = ["gpu.release"]
        path.write_text(json.dumps(invalid), encoding="utf-8")
    else:
        path.write_bytes(b" " * (64 * 1024 + 1))

    with pytest.raises(OwnerRegistryLoadError):
        load_owner_review_registry(tmp_path)


def test_missing_file_cannot_be_overridden_by_untrusted_env(tmp_path, monkeypatch):
    # 即使传入 JSON 字符串，也不会将环境内容提升为 Owner 权限配置。
    monkeypatch.setenv(
        "PICOTOO_OWNER_REVIEW_REGISTRY",
        json.dumps(_valid_registry(secrets.token_urlsafe(32))),
    )
    assert load_owner_review_registry(tmp_path).credentials == ()
