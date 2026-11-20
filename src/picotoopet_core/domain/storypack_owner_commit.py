"""Exact-SHA Owner storyboard review built on existing Core audit and idempotency tables.

The only decision recorded here is the Owner's STORYBOARD REVIEW. It does not
approve the underlying MASTER rights, grant GPU use, or queue an Episode.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from picotoopet_core.audit.writer import AuditWriter, canonical_hash
from picotoopet_core.db.database import Database
from picotoopet_core.domain.storypack import StoryPackV1, storypack_preview
from picotoopet_core.domain.storypack_assets import inspect_recorded_asset_refs
from picotoopet_core.domain.storypack_owner_subject import build_owner_review_subject
from picotoopet_core.security.owner_principal import OwnerPrincipal

_COMMIT_ACTION = "studio.storypack.storyboard_review.commit"
_REVOKE_ACTION = "studio.storypack.storyboard_review.revoke"
_RESOURCE_TYPE = "storypack.storyboard_review"
_IDEMPOTENCY_TYPE = "storypack.storyboard_review"


class StoryboardReviewError(ValueError):
    """A stable fail-closed error; the caller maps it to an HTTP conflict."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _digest(document: dict) -> str:
    # 统一 JSON 序列化，拒绝非有限数字，避免相同审批生成不同指纹。
    return hashlib.sha256(
        json.dumps(
            document, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _grant_ref(principal: OwnerPrincipal) -> str:
    # 不存储真实 Owner Token 或明文凭据 ID，只记录当前凭据的稳定摘要。
    return hashlib.sha256(principal.credential_id.encode("utf-8")).hexdigest()


def _read_event(connection, review_id: str):
    row = connection.execute(
        "SELECT * FROM audit_events WHERE audit_id=? AND action=?",
        (review_id, _COMMIT_ACTION),
    ).fetchone()
    if row is None:
        raise StoryboardReviewError("OWNER_STORYBOARD_REVIEW_NOT_FOUND")
    try:
        details = json.loads(row["details_redacted_json"])
        reconstructed = {
            "audit_id": row["audit_id"],
            "trace_id": row["trace_id"],
            "actor_type": row["actor_type"],
            "actor_id": row["actor_id"],
            "action": row["action"],
            "resource_type": row["resource_type"],
            "resource_id": row["resource_id"],
            "decision": row["decision"],
            "reason_code": row["reason_code"],
            "details_redacted_json": row["details_redacted_json"],
            "previous_hash": row["previous_hash"],
            "created_at": row["created_at"],
        }
        if (
            not isinstance(details, dict)
            or row["resource_type"] != _RESOURCE_TYPE
            or row["decision"] != "STORYBOARD_ONLY"
            or not hmac.compare_digest(canonical_hash(reconstructed), row["event_hash"])
        ):
            raise ValueError("invalid audit evidence")
    except (ValueError, TypeError, KeyError) as exc:
        raise StoryboardReviewError("OWNER_STORYBOARD_AUDIT_INVALID") from exc
    return row, details


class StoryboardReviewService:
    """Review and verify an immutable story subject without changing the task queue."""

    def __init__(self, database: Database, objects_dir: Path) -> None:
        self.database = database
        self.objects_dir = objects_dir
        self.audit = AuditWriter(database)

    def subject(self, pack: StoryPackV1) -> dict:
        # 重新读取并哈希 Mac 自管理素材，不能信任客户端提交的检查结果。
        preview = storypack_preview(pack)
        checks = inspect_recorded_asset_refs(
            self.database, preview["unresolved_asset_refs"],
            managed_objects_dir=self.objects_dir,
        )
        subject = build_owner_review_subject(pack, preview["storypack_sha256"], checks)
        return {
            "storypack_sha256": preview["storypack_sha256"],
            "review": subject,
            "can_queue": False,
            "gpu_authorized": False,
        }

    def commit(
        self,
        *,
        pack: StoryPackV1,
        subject_key: str,
        expected_subject_sha256: str,
        principal: OwnerPrincipal,
        idempotency_key: str,
        expires_seconds: int,
    ) -> dict:
        if not 10 <= len(idempotency_key) <= 200:
            raise StoryboardReviewError("OWNER_STORYBOARD_IDEMPOTENCY_KEY_INVALID")
        key_ref = "storyboard:" + hashlib.sha256(idempotency_key.encode()).hexdigest()
        with self.database.transaction() as connection:
            prepared = self.subject(pack)
            review = prepared["review"]
            current = review["subject_sha256"]
            if current is None:
                raise StoryboardReviewError("OWNER_STORYBOARD_ASSETS_UNVERIFIED")
            if not hmac.compare_digest(current, expected_subject_sha256):
                raise StoryboardReviewError("OWNER_STORYBOARD_SUBJECT_STALE")

            request_sha256 = _digest({
                "subject_key": subject_key,
                "subject_sha256": current,
                "grant_ref": _grant_ref(principal),
                "actor_id": principal.actor_id,
                "registry_revision": principal.registry_revision,
                "expires_seconds": expires_seconds,
            })
            previous = connection.execute(
                "SELECT resource_id FROM idempotency_keys "
                "WHERE idempotency_key=? AND resource_type=?",
                (key_ref, _IDEMPOTENCY_TYPE),
            ).fetchone()
            if previous is not None:
                row, details = _read_event(connection, previous["resource_id"])
                if details.get("request_sha256") != request_sha256:
                    raise StoryboardReviewError("OWNER_STORYBOARD_IDEMPOTENCY_CONFLICT")
                self._verify_event(connection, row, details, prepared, subject_key, principal)
                return self._receipt(row["audit_id"], prepared, "STORYBOARD_ONLY_ALREADY_REVIEWED")

            expires = (datetime.now(UTC) + timedelta(seconds=expires_seconds)).isoformat()
            review_id = self.audit.append(
                trace_id=current, actor_type="owner_principal",
                actor_id=principal.actor_id, action=_COMMIT_ACTION,
                resource_type=_RESOURCE_TYPE, resource_id=current,
                decision="STORYBOARD_ONLY", reason_code=None,
                details={
                    "subject_key": subject_key,
                    "storypack_sha256": prepared["storypack_sha256"],
                    "subject_sha256": current,
                    "grant_ref": _grant_ref(principal),
                    "registry_revision": principal.registry_revision,
                    "expires_at": expires,
                    "request_sha256": request_sha256,
                },
                connection=connection,
            )
            connection.execute(
                "INSERT INTO idempotency_keys "
                "(idempotency_key, resource_type, resource_id, created_at) "
                "VALUES (?, ?, ?, ?)",
                (key_ref, _IDEMPOTENCY_TYPE, review_id, datetime.now(UTC).isoformat()),
            )
        return self._receipt(review_id, prepared, "STORYBOARD_ONLY_REVIEWED")

    @staticmethod
    def _receipt(review_id: str, prepared: dict, status: str) -> dict:
        return {
            "review_id": review_id, "status": status,
            "subject_sha256": prepared["review"]["subject_sha256"],
            "storypack_sha256": prepared["storypack_sha256"],
            "master_rights_approved": False,
            "gpu_authorized": False, "can_queue": False,
        }

    @staticmethod
    def _verify_event(connection, row, details: dict, prepared: dict,
                      subject_key: str, principal: OwnerPrincipal) -> None:
        current = prepared["review"]["subject_sha256"]
        if current is None or not (
            details.get("subject_key") == subject_key
            and details.get("storypack_sha256") == prepared["storypack_sha256"]
            and details.get("subject_sha256") == current
            and row["resource_id"] == current
            and row["actor_id"] == principal.actor_id
            and details.get("grant_ref") == _grant_ref(principal)
            and details.get("registry_revision") == principal.registry_revision
        ):
            raise StoryboardReviewError("OWNER_STORYBOARD_REVIEW_STALE")
        try:
            expiry = datetime.fromisoformat(details["expires_at"])
            if expiry.tzinfo is None or datetime.now(UTC) >= expiry:
                raise StoryboardReviewError("OWNER_STORYBOARD_REVIEW_EXPIRED")
        except (KeyError, TypeError, ValueError) as exc:
            raise StoryboardReviewError("OWNER_STORYBOARD_REVIEW_EXPIRED") from exc
        if connection.execute(
            "SELECT 1 FROM audit_events WHERE action=? AND resource_id=? LIMIT 1",
            (_REVOKE_ACTION, row["audit_id"]),
        ).fetchone() is not None:
            raise StoryboardReviewError("OWNER_STORYBOARD_REVIEW_REVOKED")

    def verify(
        self, *, pack: StoryPackV1, subject_key: str,
        review_id: str, principal: OwnerPrincipal,
    ) -> dict:
        # 生产准入仍必须独立复核；此调用只确认故事分镜审核有效。
        prepared = self.subject(pack)
        with self.database.transaction() as connection:
            row, details = _read_event(connection, review_id)
            self._verify_event(connection, row, details, prepared, subject_key, principal)
        return self._receipt(review_id, prepared, "STORYBOARD_ONLY_CURRENT")

    def revoke(
        self, *, subject_key: str, review_id: str, principal: OwnerPrincipal,
    ) -> dict:
        with self.database.transaction() as connection:
            row, details = _read_event(connection, review_id)
            if details.get("subject_key") != subject_key:
                raise StoryboardReviewError("OWNER_STORYBOARD_SCOPE_MISMATCH")
            if connection.execute(
                "SELECT 1 FROM audit_events WHERE action=? AND resource_id=? LIMIT 1",
                (_REVOKE_ACTION, review_id),
            ).fetchone() is None:
                self.audit.append(
                    trace_id=review_id, actor_type="owner_principal",
                    actor_id=principal.actor_id, action=_REVOKE_ACTION,
                    resource_type=_RESOURCE_TYPE, resource_id=review_id,
                    decision="REVOKED", reason_code="OWNER_REVOKED",
                    details={"subject_key": subject_key},
                    connection=connection,
                )
        return {"review_id": review_id, "status": "REVOKED", "can_queue": False}
