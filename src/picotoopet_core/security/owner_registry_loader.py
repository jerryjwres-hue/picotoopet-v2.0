"""Fail-closed, default-off Owner credential registry from a trusted Mac local file.

Mac Core stores only token hashes here, never plaintext Owner tokens. No device
Bearer, mobile session, request body or untrusted asset metadata can supply grants.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from pydantic import ValidationError

from picotoopet_core.security.owner_principal import OwnerReviewRegistry

_MAX_REGISTRY_BYTES = 64 * 1024
_FILE_NAME = "owner_review_registry.json"


class OwnerRegistryLoadError(ValueError):
    """Invalid operator-controlled Owner registry, intentionally no secrets in errors."""


def _unique_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    # 重复 JSON key 可能隐藏权限替换，不能采用默认的后者覆盖前者语义。
    mapping: dict[str, object] = {}
    for key, value in pairs:
        if key in mapping:
            raise OwnerRegistryLoadError("OWNER_REVIEW_REGISTRY_DUPLICATE_KEY")
        mapping[key] = value
    return mapping


def load_owner_review_registry(runtime_root: Path) -> OwnerReviewRegistry:
    """Read only a local user-owned 0600 regular file; never create or provision one."""
    state_dir = runtime_root / "state"
    target = state_dir / _FILE_NAME

    # 原有安装通常没有此文件；缺失时保持 Owner 审批完全禁用。
    if not target.exists() and not target.is_symlink():
        return OwnerReviewRegistry()

    # 不允许状态目录或凭据文件的软链接将授权来源换成外部对象。
    if state_dir.is_symlink() or target.is_symlink():
        raise OwnerRegistryLoadError("OWNER_REVIEW_REGISTRY_SYMLINK_FORBIDDEN")

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(target, flags)
        with os.fdopen(descriptor, "rb") as handle:
            metadata = os.fstat(handle.fileno())
            uid = getattr(os, "getuid", lambda: None)()
            if (
                not stat.S_ISREG(metadata.st_mode)
                or (uid is not None and metadata.st_uid != uid)
                or bool(stat.S_IMODE(metadata.st_mode) & 0o077)
            ):
                raise OwnerRegistryLoadError("OWNER_REVIEW_REGISTRY_PERMISSIONS_INVALID")
            if metadata.st_size > _MAX_REGISTRY_BYTES:
                raise OwnerRegistryLoadError("OWNER_REVIEW_REGISTRY_TOO_LARGE")
            raw = handle.read(_MAX_REGISTRY_BYTES + 1)
            if len(raw) > _MAX_REGISTRY_BYTES:
                raise OwnerRegistryLoadError("OWNER_REVIEW_REGISTRY_TOO_LARGE")
    except OwnerRegistryLoadError:
        raise
    except OSError as error:
        raise OwnerRegistryLoadError("OWNER_REVIEW_REGISTRY_UNAVAILABLE") from error

    try:
        decoded = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_json_keys)
        return OwnerReviewRegistry.model_validate(decoded)
    except OwnerRegistryLoadError:
        raise
    except (UnicodeError, ValueError, TypeError, ValidationError, RecursionError) as error:
        raise OwnerRegistryLoadError("OWNER_REVIEW_REGISTRY_INVALID") from error
