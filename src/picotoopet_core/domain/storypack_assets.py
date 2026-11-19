"""Read-only registry diagnostics for StoryPack asset references.

A database record is NOT proof of ownership, valid image bytes, or owner approval.
The existing artifacts table remains the only indexed source; no secondary registry.
"""

from __future__ import annotations

import re

from picotoopet_core.db.database import Database

_SHA256_HEX = re.compile(r"^[a-fA-F0-9]{64}$")


def inspect_recorded_asset_refs(database: Database, refs: list[str]) -> list[dict]:
    """Check exact artifact IDs in SQLite without reading files or creating privileges."""
    checks = []
    for ref in dict.fromkeys(refs):
        # All refs are validated as AssetRef by StoryPackV1 before this query.
        row = database.fetchone(
            "SELECT artifact_type, sha256, is_original FROM artifacts WHERE artifact_id = ?",
            (ref,),
        )
        if row is None:
            status = "RECORD_NOT_FOUND"
            has_digest = False
            is_original = False
            category = None
        else:
            has_digest = (
                isinstance(row["sha256"], str)
                and _SHA256_HEX.fullmatch(row["sha256"]) is not None
            )
            status = "RECORDED_UNAPPROVED" if has_digest else "RECORD_HASH_MISSING"
            is_original = row["is_original"] == 1
            category = row["artifact_type"]

        checks.append(
            {
                "ref": ref,
                "registry_record_status": status,
                "sha256_recorded": has_digest,
                "original_flag_recorded": is_original,
                "artifact_type": category,
                # 现有 artifacts 表无授权证据，不得借存在性查询完成主人审批。
                "owner_approval_verified": False,
                "content_integrity_verified": False,
                "physical_file_verified": False,
                "usable_for_generation": False,
            }
        )

    return checks
