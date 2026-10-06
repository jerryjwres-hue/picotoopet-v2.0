"""Strict contracts for image-only trusted asset ingress (C006B1)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MANAGED_ROOT_ID = "windows.comfy-input.v1"
SOURCE_KIND = "windows_user_import.v1"
MAX_ASSET_BYTES = 50_000_000
MAX_IMAGE_DIMENSION = 16_384

ScopeKind = Literal["autonomous_goal", "project"]
MediaType = Literal["image/png", "image/jpeg"]

_EXTENSIONS: dict[str, str] = {"image/png": "png", "image/jpeg": "jpg"}
_SCOPE_ID_PATTERN = r"^[A-Za-z0-9_.-]+$"


def derive_scope_key(scope_kind: str, scope_id: str) -> str:
    """Core-derived owner key; callers never supply it."""

    return (
        f"autonomous-goal:{scope_id}" if scope_kind == "autonomous_goal" else f"project:{scope_id}"
    )


def derive_managed_relpath(sha256: str, media_type: str) -> str:
    """Canonical content-addressed relative path; never caller-chosen."""

    return f"PicotooPet/assets/v1/{sha256[:2]}/{sha256}.{_EXTENSIONS[media_type]}"


class TrustedAssetRegisterRequestV1(BaseModel):
    """Bounded registration facts only; unknown fields (paths/URLs/ids) are rejected."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    scope_kind: ScopeKind
    scope_id: str = Field(min_length=1, max_length=120, pattern=_SCOPE_ID_PATTERN)
    idempotency_key: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_.:-]+$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0, le=MAX_ASSET_BYTES)
    media_type: MediaType
    width: int = Field(ge=1, le=MAX_IMAGE_DIMENSION)
    height: int = Field(ge=1, le=MAX_IMAGE_DIMENSION)
    duration_ms: None = None
    managed_root_id: Literal["windows.comfy-input.v1"]
    source_kind: Literal["windows_user_import.v1"]


class TrustedAssetProvenanceV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_kind: Literal["windows_user_import.v1"]
    byte_authority: Literal["windows"] = "windows"
    bytes_in_core: Literal[False] = False


class TrustedAssetRecordV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    asset_id: str
    scope_kind: ScopeKind
    scope_id: str
    scope_key: str
    artifact_type: Literal["image"]
    classification: Literal["INTERNAL"]
    managed_root_id: Literal["windows.comfy-input.v1"]
    managed_relpath: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0, le=MAX_ASSET_BYTES)
    media_type: MediaType
    width: int = Field(ge=1, le=MAX_IMAGE_DIMENSION)
    height: int = Field(ge=1, le=MAX_IMAGE_DIMENSION)
    duration_ms: None = None
    source_kind: Literal["windows_user_import.v1"]
    provenance: TrustedAssetProvenanceV1
    cloud_policy: Literal["local_only"]
    created_at: datetime
