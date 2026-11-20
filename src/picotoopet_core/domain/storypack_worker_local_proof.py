"""One-use Worker-local image proof for an existing frozen Owner Episode.

A distinct Worker HMAC secret authenticates a report of real Windows file hashes.
It does NOT authorize GPU leases, grant rights, or certify the remote hardware.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from picotoopet_core.audit.writer import AuditWriter, canonical_hash
from picotoopet_core.db.database import Database
from picotoopet_core.domain.episode import Episode
from picotoopet_core.domain.storypack_assets import inspect_recorded_asset_refs
from picotoopet_core.domain.storypack_frame_sources import validate_episode_frame_manifest
from picotoopet_core.domain.storypack_master_evidence import (
    MasterEvidenceError, MasterEvidenceService, _event,
)

_PROOF_CONTRACT = "picotoo.worker-local-sha-proof.v1"
_TTL = 120


class WorkerProofError(ValueError):
    """Stable fail-closed code without paths or key material."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _sha_json(value: dict | list) -> str:
    # Core 和 Worker 共用按键排序的规范化 JSON，不使用平台特定的路径编码。
    canonical = json.dumps(
        value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def proof_message(*, nonce: str, worker_id: str, episode_id: str,
                  frozen_plan_sha256: str, source_bindings_sha256: str,
                  bindings_sha256: str) -> dict:
    """Pure signed contract; no arbitrary file path or client-supplied Plan content."""
    return {
        "contract": _PROOF_CONTRACT,
        "nonce": nonce,
        "worker_id": worker_id,
        "episode_id": episode_id,
        "frozen_plan_sha256": frozen_plan_sha256,
        "source_bindings_sha256": source_bindings_sha256,
        "bindings_sha256": bindings_sha256,
    }


class WorkerProofRegistry:
    """Single process-local challenge, audit-backed receipt, no new scheduler or DB."""

    def __init__(self, *, database: Database, objects_dir: Path,
                 worker_id: str | None, worker_secret: str | None) -> None:
        self.database = database
        self.objects_dir = objects_dir
        self.worker_id = worker_id
        self._secret = worker_secret.encode("ascii") if worker_secret else None
        self._lock = threading.RLock()
        self._pending: dict | None = None

    @property
    def configured(self) -> bool:
        return self._secret is not None and bool(self.worker_id)

    def _current_target(self, db, episode_id: str) -> dict:
        """Rebuild from actual Core freeze, stage audit and immutable keyframe tasks."""
        plan = MasterEvidenceService._frozen(db, episode_id)
        plan_sha = canonical_hash(plan)
        stage_rows = db.execute(
            "SELECT audit_id FROM audit_events "
            "WHERE action='episode.windows_staging_report' AND resource_id=?",
            (episode_id,),
        ).fetchall()
        if len(stage_rows) != 1:
            raise WorkerProofError("WORKER_STAGING_REPORT_REQUIRED")
        stage, details = _event(db, stage_rows[0]["audit_id"],
                                "episode.windows_staging_report")
        if (stage["decision"] != "DATA_REPORTED_GPU_HOLD"
                or details.get("frozen_plan_sha256") != plan_sha
                or details.get("source_bindings_sha256")
                != plan["source_bindings_sha256"]):
            raise WorkerProofError("WORKER_STAGING_FROZEN_PLAN_STALE")

        saved = db.execute(
            "SELECT spec_json FROM production_episodes WHERE episode_id=?",
            (episode_id,),
        ).fetchone()
        if saved is None:
            raise WorkerProofError("WORKER_FROZEN_EPISODE_MISSING")
        episode = Episode.model_validate_json(saved["spec_json"])
        if canonical_hash(episode.model_dump(mode="json")) != plan["episode_sha256"]:
            raise WorkerProofError("WORKER_EPISODE_SHA_CHANGED")

        rows = db.execute(
            "SELECT payload_json FROM tasks WHERE task_type='gen.keyframe' "
            "AND json_extract(payload_json, '$.episode_id')=? ORDER BY rowid",
            (episode_id,),
        ).fetchall()
        if len(rows) != len(episode.shots):
            raise WorkerProofError("WORKER_KEYFRAME_TASKS_CHANGED")
        source_sha = plan["source_bindings_sha256"]
        manifest = None
        for index, row in enumerate(rows):
            payload = json.loads(row["payload_json"])
            jobs = payload["jobs"]
            if (payload["shot_id"] != episode.shots[index].shot_id
                    or jobs.get("source_bindings_sha256") != source_sha):
                raise WorkerProofError("WORKER_TASK_BINDINGS_CHANGED")
            if manifest is None:
                manifest = jobs.get("frame_source_manifest")
            elif manifest != jobs.get("frame_source_manifest"):
                raise WorkerProofError("WORKER_TASK_MANIFEST_CHANGED")
        try:
            normalized = validate_episode_frame_manifest(episode, manifest, source_sha)
        except ValueError as error:
            raise WorkerProofError("WORKER_FRAME_MANIFEST_INVALID") from error
        if normalized["storypack_sha256"] != plan["storypack_sha256"]:
            raise WorkerProofError("WORKER_STORYPACK_CHANGED")

        bindings = sorted(
            normalized["bindings"],
            key=lambda row: (row["shot_id"], row["role"], row["asset_ref"]),
        )
        if (not bindings
                or len(bindings) != details.get("staged_binding_count")
                or details.get("source_bindings_sha256") != source_sha):
            raise WorkerProofError("WORKER_STAGED_BINDING_COUNT_CHANGED")

        expected = {}
        for item in bindings:
            ref = item["asset_ref"]
            sha = item["managed_sha256"]
            if ref in expected and expected[ref] != sha:
                raise WorkerProofError("WORKER_ASSET_REF_COLLISION")
            expected[ref] = sha
        checks = inspect_recorded_asset_refs(
            self.database, sorted(expected),
            managed_objects_dir=self.objects_dir,
        )
        if any(
            row["recorded_sha256"] != expected[row["ref"]]
            or row["content_integrity_verified"] is not True
            for row in checks
        ):
            raise WorkerProofError("WORKER_MAC_SOURCE_SHA_CHANGED")
        return {
            "episode_id": episode_id,
            "frozen_plan_sha256": plan_sha,
            "source_bindings_sha256": source_sha,
            "bindings": bindings,
            "bindings_sha256": _sha_json(bindings),
        }

    def _next_target(self, db) -> dict | None:
        frozen = db.execute(
            "SELECT resource_id FROM audit_events "
            "WHERE action='episode.freeze_owner_hold' ORDER BY rowid",
        ).fetchall()
        for row in frozen:
            episode_id = row["resource_id"]
            staged = db.execute(
                "SELECT 1 FROM audit_events WHERE action='episode.windows_staging_report' "
                "AND resource_id=? LIMIT 1",
                (episode_id,),
            ).fetchone()
            if staged is None:
                continue
            target = self._current_target(db, episode_id)
            # A successful report does not authorize GPU; do not ask for it repeatedly.
            previous = db.execute(
                "SELECT details_redacted_json FROM audit_events "
                "WHERE action='episode.worker_local_proof' AND resource_id=?",
                (episode_id,),
            ).fetchall()
            if len(previous) > 1:
                raise WorkerProofError("WORKER_PROOF_AUDIT_DUPLICATE")
            if previous:
                prior = json.loads(previous[0]["details_redacted_json"])
                if (prior.get("frozen_plan_sha256") != target["frozen_plan_sha256"]
                        or prior.get("source_bindings_sha256")
                        != target["source_bindings_sha256"]
                        or prior.get("bindings_sha256") != target["bindings_sha256"]
                        or prior.get("worker_id") != self.worker_id):
                    raise WorkerProofError("WORKER_PROOF_EXISTING_CONFLICT")
                continue
            return target
        return None

    def claim(self, worker_id: str) -> dict | None:
        """Offer one challenge to the configured Worker, never to arbitrary IDs."""
        with self._lock:
            if not self.configured:
                return None
            if worker_id != self.worker_id:
                raise WorkerProofError("WORKER_ID_NOT_REGISTERED")
            now = time.monotonic()
            if self._pending is not None:
                if self._pending["expires"] > now:
                    return self._pending["response"]
                self._pending = None
            with self.database.transaction() as db:
                target = self._next_target(db)
            if target is None:
                return None
            nonce = secrets.token_urlsafe(32)
            response = {
                **target,
                "nonce": nonce,
                "worker_id": worker_id,
                "expires_in_seconds": _TTL,
                "can_lease": False,
                "gpu_authorized": False,
            }
            self._pending = {
                "nonce": nonce,
                "expires": now + _TTL,
                "response": response,
            }
            return response

    def submit(self, payload: dict) -> dict:
        """Require a distinct Worker secret, actual source set, fresh challenge."""
        with self._lock:
            challenge = self._pending
            # A failed submission consumes this challenge, preventing guessing/replay.
            self._pending = None
            if (challenge is None
                    or challenge["expires"] <= time.monotonic()
                    or not self.configured):
                raise WorkerProofError("WORKER_PROOF_CHALLENGE_EXPIRED")
            target = challenge["response"]
            expected = proof_message(
                nonce=target["nonce"],
                worker_id=target["worker_id"],
                episode_id=target["episode_id"],
                frozen_plan_sha256=target["frozen_plan_sha256"],
                source_bindings_sha256=target["source_bindings_sha256"],
                bindings_sha256=target["bindings_sha256"],
            )
            if any(payload.get(key) != value for key, value in expected.items()):
                raise WorkerProofError("WORKER_PROOF_TARGET_MISMATCH")
            claimed = payload.get("signature")
            if not isinstance(claimed, str) or len(claimed) != 64:
                raise WorkerProofError("WORKER_PROOF_SIGNATURE_INVALID")
            expected_hmac = hmac.new(
                self._secret, _sha_json(expected).encode("ascii"), hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(claimed, expected_hmac):
                raise WorkerProofError("WORKER_PROOF_SIGNATURE_INVALID")
            with self.database.transaction() as db:
                actual = self._current_target(db, target["episode_id"])
                if any(actual[key] != target[key] for key in (
                    "episode_id", "frozen_plan_sha256",
                    "source_bindings_sha256", "bindings_sha256",
                )):
                    raise WorkerProofError("WORKER_PROOF_FROZEN_SOURCE_CHANGED")
                existing = db.execute(
                    "SELECT 1 FROM audit_events "
                    "WHERE action='episode.worker_local_proof' AND resource_id=?",
                    (target["episode_id"],),
                ).fetchone()
                if existing:
                    raise WorkerProofError("WORKER_PROOF_ALREADY_RECORDED")
                AuditWriter(self.database).append(
                    connection=db, trace_id=target["frozen_plan_sha256"],
                    actor_type="worker_hmac", actor_id=target["worker_id"],
                    action="episode.worker_local_proof", resource_type="episode",
                    resource_id=target["episode_id"],
                    decision="WORKER_AUTHENTICATED_DATA_REPORT_GPU_HOLD",
                    reason_code="INDEPENDENT_ADMISSION_NOT_GRANTED",
                    details={
                        "worker_id": target["worker_id"],
                        "frozen_plan_sha256": target["frozen_plan_sha256"],
                        "source_bindings_sha256": target["source_bindings_sha256"],
                        "bindings_sha256": target["bindings_sha256"],
                        "challenge_sha256": hashlib.sha256(
                            target["nonce"].encode("ascii")
                        ).hexdigest(),
                    },
                )
            return {
                "status": "WORKER_HMAC_SOURCE_REPORT_ACCEPTED_GPU_HOLD",
                "episode_id": target["episode_id"],
                "frozen_plan_sha256": target["frozen_plan_sha256"],
                "worker_authenticated": True,
                "real_windows_sha_reported": True,
                "hardware_attestation": False,
                "can_lease": False,
                "gpu_authorized": False,
            }
