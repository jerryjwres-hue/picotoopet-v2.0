"""Scoped owner-review credentials; independent from Mac Core device pairing.

This module is intentionally pure: a configuration or Bearer string cannot itself approve
facts, create Goals or grant GPU capability. Production credential provisioning is separate.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_SUBJECT_PATTERN = r"^pet:[a-z0-9][a-z0-9-]{1,63}$"
_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$"
_FINGERPRINT_PATTERN = r"^[0-9a-f]{64}$"


class OwnerCredentialConfig(BaseModel):
    """Operator-controlled authorization for ONE independently provisioned secret."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    credential_id: str = Field(pattern=_ID_PATTERN, max_length=80)
    actor_id: str = Field(pattern=_ID_PATTERN, max_length=80)
    token_sha256: str = Field(pattern=_FINGERPRINT_PATTERN)
    subject_keys: tuple[str, ...] = Field(min_length=1, max_length=32)
    permissions: tuple[Literal["owner_facts.review"], ...] = ()
    registry_revision: int = Field(ge=1)
    enabled: bool = False
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def _validate_grant(self) -> OwnerCredentialConfig:
        if any(
            not re.fullmatch(_SUBJECT_PATTERN, key)
            for key in self.subject_keys
        ) or len(set(self.subject_keys)) != len(self.subject_keys):
            raise ValueError("OWNER_REVIEW_SUBJECT_SCOPE_INVALID")
        if len(set(self.permissions)) != len(self.permissions):
            raise ValueError("OWNER_REVIEW_PERMISSION_DUPLICATE")
        if self.expires_at is not None and self.expires_at.tzinfo is None:
            raise ValueError("OWNER_REVIEW_EXPIRY_MUST_BE_AWARE")
        return self


class OwnerReviewRegistry(BaseModel):
    """Strict, optional local registry; empty means review authentication is OFF."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["owner_review_registry.v1"] = "owner_review_registry.v1"
    credentials: tuple[OwnerCredentialConfig, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def _unique_credentials(self) -> OwnerReviewRegistry:
        ids = [item.credential_id for item in self.credentials]
        fingerprints = [item.token_sha256 for item in self.credentials]
        if len(set(ids)) != len(ids) or len(set(fingerprints)) != len(fingerprints):
            raise ValueError("OWNER_REVIEW_CREDENTIAL_REGISTRY_CONFLICT")
        return self


class OwnerPrincipal(BaseModel):
    """Server-derived capability, never taken from client-controlled fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    actor_id: str
    credential_id: str
    subject_keys: tuple[str, ...]
    permissions: tuple[Literal["owner_facts.review"], ...]
    registry_revision: int


class OwnerAuthFailure(ValueError):
    def __init__(self, status_code: int, code: str) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code


def owner_token_fingerprint(token: str) -> str:
    """Fingerprint an externally generated >=256-bit random Bearer token."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def resolve_owner_principal(
    *,
    supplied_token: str | None,
    device_token: str,
    registry: OwnerReviewRegistry,
    now: datetime | None = None,
) -> OwnerPrincipal:
    """Recognize only a separate owner credential; never promote the device token."""

    if supplied_token is None:
        raise OwnerAuthFailure(401, "OWNER_REVIEW_AUTHENTICATION_REQUIRED")
    if hmac.compare_digest(supplied_token, device_token):
        raise OwnerAuthFailure(403, "OWNER_REVIEW_DEVICE_TOKEN_FORBIDDEN")
    if len(supplied_token) < 43 or len(supplied_token) > 256:
        raise OwnerAuthFailure(401, "OWNER_REVIEW_AUTHENTICATION_REQUIRED")
    if not supplied_token.isascii() or not all(
        character.isalnum() or character in "-_" for character in supplied_token
    ):
        raise OwnerAuthFailure(401, "OWNER_REVIEW_AUTHENTICATION_REQUIRED")

    fingerprint = owner_token_fingerprint(supplied_token)
    matches = [
        entry for entry in registry.credentials
        if hmac.compare_digest(fingerprint, entry.token_sha256)
    ]
    if len(matches) != 1:
        raise OwnerAuthFailure(401, "OWNER_REVIEW_AUTHENTICATION_REQUIRED")
    grant = matches[0]
    instant = now if now is not None else datetime.now(UTC)
    if not grant.enabled or (
        grant.expires_at is not None and instant >= grant.expires_at
    ):
        raise OwnerAuthFailure(401, "OWNER_REVIEW_CREDENTIAL_DISABLED")
    return OwnerPrincipal(
        actor_id=grant.actor_id,
        credential_id=grant.credential_id,
        subject_keys=grant.subject_keys,
        permissions=grant.permissions,
        registry_revision=grant.registry_revision,
    )


def require_owner_scope(principal: OwnerPrincipal, subject_key: str) -> None:
    """Authorization is a Core-granted, exact subject+permission intersection."""

    if (
        subject_key not in principal.subject_keys
        or "owner_facts.review" not in principal.permissions
    ):
        raise OwnerAuthFailure(403, "OWNER_REVIEW_SCOPE_FORBIDDEN")


def require_owner_actor(principal: OwnerPrincipal, review_actor_id: str) -> None:
    """Reject a stale/other actor when a review is resumed or committed."""

    if not hmac.compare_digest(principal.actor_id, review_actor_id):
        raise OwnerAuthFailure(403, "OWNER_REVIEW_ACTOR_MISMATCH")
