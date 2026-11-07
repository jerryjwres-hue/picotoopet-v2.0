"""Read a locally protected, default-off owner-review registry.

The registry contains only token fingerprints and scoped actor metadata. A privileged secret
is never read from an environment variable or committed to a repository. Enabled credentials
must also be explicitly provisioned into the current Mac user's Keychain.
"""

from __future__ import annotations

import hmac
import os
import stat
from pathlib import Path

from picotoopet_core.security.owner_principal import (
    OwnerReviewRegistry,
    owner_token_fingerprint,
)

from .keychain import read_api_token_from_keychain

_MAX_REGISTRY_BYTES = 64 * 1024


def load_owner_review_registry(path_value: str | None) -> OwnerReviewRegistry:
    """Fail closed when the protected file or required Keychain secret is unavailable."""

    disabled = OwnerReviewRegistry()
    if not path_value:
        return disabled
    path = Path(path_value).expanduser()
    if not path.is_absolute() or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "getuid"):
        return disabled
    try:
        # Open atomically without symlink following; only the current user may read it.
        flags = os.O_RDONLY | os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            metadata = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.getuid()
                or (metadata.st_mode & 0o077) != 0
                or metadata.st_size > _MAX_REGISTRY_BYTES
            ):
                return disabled
            raw = handle.read(_MAX_REGISTRY_BYTES + 1)
            if len(raw) > _MAX_REGISTRY_BYTES:
                return disabled
        configured = OwnerReviewRegistry.model_validate_json(raw)

        verified = []
        for grant in configured.credentials:
            if not grant.enabled:
                verified.append(grant)
                continue
            # Never use the generic device token as an owner-review Keychain secret.
            secret = read_api_token_from_keychain(
                service=f"PicotooPetV2.OwnerReview.{grant.credential_id}"
            )
            valid_secret = (
                secret is not None
                and len(secret) >= 43
                and secret.isascii()
                and all(character.isalnum() or character in "-_" for character in secret)
                and hmac.compare_digest(owner_token_fingerprint(secret), grant.token_sha256)
            )
            verified.append(
                grant if valid_secret else grant.model_copy(update={"enabled": False})
            )
        return OwnerReviewRegistry(credentials=tuple(verified))
    except (OSError, ValueError, UnicodeError):
        # Absence, malformed JSON, invalid permissions or missing Keychain all disable review.
        return disabled
