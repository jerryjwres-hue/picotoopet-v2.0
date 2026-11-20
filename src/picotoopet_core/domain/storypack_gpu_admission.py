"""One frozen Episode, one existing Worker, one scoped and revocable GPU lease path.

Default-off. All authorization is checked inside the existing SQLite queue transaction.
No new executor, scheduler, task table, or data-plane GPU operation is introduced.
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
from picotoopet_core.domain.executor import GPU_TAG, TASK_RUNNERS, ExecutorLease
from picotoopet_core.domain.storypack_master_evidence import (
    MasterEvidenceClaim, MasterEvidenceError, MasterEvidenceService,
    _current_event, _event,
)
from picotoopet_core.domain.storypack_worker_local_proof import (
    WorkerProofError, WorkerProofRegistry,
)
from picotoopet_core.security.owner_principal import (
    OwnerPrincipal, OwnerAuthFailure, require_owner_scope,
)
from picotoopet_core.domain.enums import TaskStatus

_ADMIT = "episode.scoped_gpu_admission"
_REVOKE = "episode.scoped_gpu_admission.revoke"
_LEASE = "episode.scoped_gpu_lease_granted"
_MASTER = "studio.storypack.master_source.review"
_MASTER_REVOKE = "studio.storypack.master_source.revoke"
_WORKER = "episode.worker_local_proof"
_LEASE_CONTRACT = "picotoo.scoped-worker-lease.v1"


class AdmissionError(ValueError):
    """Stable denial code. Errors never include local paths or private tokens."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _hash_message(message: dict) -> bytes:
    # Worker 和 Core 一致的序列化规则：仅对规范化 JSON 的 SHA-256 签名。
    return canonical_hash(message).encode("ascii")


def _scope(grant, subject: str, permission: str) -> bool:
    return (
        grant.enabled
        and subject in grant.subject_keys
        and permission in grant.permissions
        and (grant.expires_at is None or datetime.now(UTC) < grant.expires_at)
    )


class ScopedProductionAdmission:
    """Validate source/rights/proof again before every one-task Core GPU lease."""

    def __init__(self, services) -> None:
        self.services = services
        self.database = services.database
        self.audit = AuditWriter(self.database)
        self.objects = services.settings.paths.objects_dir

    def _current_owner(self, plan: dict) -> None:
        grants = [
            item for item in self.services.settings.owner_review_registry.credentials
            if item.actor_id == plan["owner_actor_id"]
            and item.registry_revision == plan["owner_registry_revision"]
            and _scope(item, plan["subject_key"], "production.admit")
        ]
        if len(grants) != 1:
            raise AdmissionError("ADMISSION_OWNER_CREDENTIAL_NOT_CURRENT")

    def _evidence(self, db, episode_id: str, master_review_id: str) -> dict:
        plan = MasterEvidenceService._frozen(db, episode_id)
        plan_sha = canonical_hash(plan)
        self._current_owner(plan)
        if not self.services.settings.worker_attestation_key:
            raise AdmissionError("ADMISSION_WORKER_SECRET_NOT_CONFIGURED")
        if not self.services.settings.worker_attestation_id:
            raise AdmissionError("ADMISSION_WORKER_ID_NOT_CONFIGURED")

        master, details = _current_event(db, master_review_id, _MASTER, _MASTER_REVOKE)
        subject = details.get("subject")
        if (master["resource_id"] != episode_id
                or master["decision"] != "HUMAN_SOURCE_REVIEW_ONLY"
                or not isinstance(subject, dict)
                or subject.get("frozen_plan_sha256") != plan_sha
                or subject.get("source_bindings_sha256") != plan["source_bindings_sha256"]
                or subject.get("reviewer_actor_id") == plan["owner_actor_id"]):
            raise AdmissionError("ADMISSION_MASTER_NOT_BOUND_TO_PLAN")
        grants = [
            item for item in self.services.settings.owner_review_registry.credentials
            if item.actor_id == subject["reviewer_actor_id"]
            and item.registry_revision == subject["reviewer_registry_revision"]
            and _scope(item, plan["subject_key"], "master.verify")
        ]
        # MASTER 审核人必须是另一名当前有效的授权主体，不能借用 Owner 身份。
        if len(grants) != 1 or master["actor_id"] != grants[0].actor_id:
            raise AdmissionError("ADMISSION_MASTER_CREDENTIAL_NOT_CURRENT")
        reviewer = OwnerPrincipal(
            actor_id=grants[0].actor_id,
            credential_id=grants[0].credential_id,
            subject_keys=grants[0].subject_keys,
            permissions=grants[0].permissions,
            registry_revision=grants[0].registry_revision,
        )
        claims = [
            MasterEvidenceClaim.model_validate(entry)
            for entry in subject["claims"]
        ]
        verified = MasterEvidenceService(self.database, self.objects)._subject(
            db, episode_id, plan_sha, plan["source_bindings_sha256"],
            reviewer, claims,
        )
        if (verified != subject
                or canonical_hash(verified) != details["review_subject_sha256"]):
            raise AdmissionError("ADMISSION_MASTER_SOURCE_REVALIDATION_FAILED")

        # Worker HMAC report must derive from the same real frozen Core sources.
        target = WorkerProofRegistry(
            database=self.database,
            objects_dir=self.objects,
            worker_id=self.services.settings.worker_attestation_id,
            worker_secret=self.services.settings.worker_attestation_key,
        )._current_target(db, episode_id)
        proof_rows = db.execute(
            "SELECT audit_id FROM audit_events "
            "WHERE action=? AND resource_id=?", (_WORKER, episode_id),
        ).fetchall()
        if len(proof_rows) != 1:
            raise AdmissionError("ADMISSION_WORKER_LOCAL_PROOF_MISSING")
        proof, proof_details = _event(db, proof_rows[0]["audit_id"], _WORKER)
        if (proof["decision"] != "WORKER_AUTHENTICATED_DATA_REPORT_GPU_HOLD"
                or proof["actor_id"] != self.services.settings.worker_attestation_id
                or proof_details.get("worker_id") != self.services.settings.worker_attestation_id
                or proof_details.get("frozen_plan_sha256") != plan_sha
                or proof_details.get("source_bindings_sha256") != target["source_bindings_sha256"]
                or proof_details.get("bindings_sha256") != target["bindings_sha256"]):
            raise AdmissionError("ADMISSION_WORKER_LOCAL_PROOF_MISMATCH")

        # Existing immutable Episode and task budgets are checked again, not an LLM flag.
        saved = self.database.fetchone(
            "SELECT spec_json FROM production_episodes WHERE episode_id=?",
            (episode_id,),
        )
        if saved is None:
            raise AdmissionError("ADMISSION_EPISODE_NOT_FOUND")
        from picotoopet_core.domain.episode import Episode
        episode = Episode.model_validate_json(saved["spec_json"])
        if not self.services.production.preview_budget(episode)["allowed"]:
            raise AdmissionError("ADMISSION_EPISODE_BUDGET_EXCEEDED")
        self._validate_static_tasks(db, episode_id, [s.shot_id for s in episode.shots])
        return {
            "episode_id": episode_id,
            "frozen_plan_sha256": plan_sha,
            "source_bindings_sha256": target["source_bindings_sha256"],
            "master_review_id": master_review_id,
            "worker_proof_id": proof["audit_id"],
            "worker_id": self.services.settings.worker_attestation_id,
            "owner_actor_id": plan["owner_actor_id"],
        }

    @staticmethod
    def _validate_static_tasks(db, episode_id: str, shots: list[str]) -> None:
        rows = db.execute(
            "SELECT task_id, task_type, parent_task_id, resource_tag, payload_json "
            "FROM tasks WHERE json_extract(payload_json, '$.episode_id')=? "
            "AND task_type IN ('gen.keyframe','gen.video','gen.foley') ORDER BY rowid",
            (episode_id,),
        ).fetchall()
        if len(rows) != 3 * len(shots):
            raise AdmissionError("ADMISSION_STATIC_TASK_SET_CHANGED")
        for index, shot_id in enumerate(shots):
            previous = None
            for task_type, task in zip(
                ("gen.keyframe", "gen.video", "gen.foley"),
                rows[3 * index:3 * index + 3], strict=True,
            ):
                payload = json.loads(task["payload_json"])
                if (task["task_type"] != task_type
                        or payload.get("shot_id") != shot_id
                        or payload.get("runner") != TASK_RUNNERS[task_type]
                        or task["resource_tag"] != GPU_TAG
                        or task["parent_task_id"] != previous):
                    raise AdmissionError("ADMISSION_STATIC_TASK_IDENTITY_CHANGED")
                previous = task["task_id"]

    def _active(self, db, episode_id: str) -> tuple[dict, dict, str]:
        entries = db.execute(
            "SELECT audit_id FROM audit_events WHERE action=? AND resource_id=?",
            (_ADMIT, episode_id),
        ).fetchall()
        if len(entries) != 1:
            raise AdmissionError("ADMISSION_NOT_PRESENT")
        row, details = _event(db, entries[0]["audit_id"], _ADMIT)
        if db.execute(
            "SELECT 1 FROM audit_events WHERE action=? AND resource_id=?",
            (_REVOKE, row["audit_id"]),
        ).fetchone():
            raise AdmissionError("ADMISSION_REVOKED")
        if row["decision"] != "SCOPED_ONE_EPISODE":
            raise AdmissionError("ADMISSION_AUDIT_CHANGED")
        expected = self._evidence(db, episode_id, details["master_review_id"])
        if any(details.get(key) != value for key, value in expected.items()):
            raise AdmissionError("ADMISSION_DEPENDENCY_STALE")
        return expected, details, row["audit_id"]

    def admit(self, episode_id: str, plan_sha: str, master_review_id: str,
              principal: OwnerPrincipal, trace_id: str) -> dict:
        with self.database.transaction() as db:
            evidence = self._evidence(db, episode_id, master_review_id)
            plan = MasterEvidenceService._frozen(db, episode_id, plan_sha)
            require_owner_scope(principal, plan["subject_key"], permission="production.admit")
            if (principal.actor_id != plan["owner_actor_id"]
                    or principal.registry_revision != plan["owner_registry_revision"]
                    or evidence["frozen_plan_sha256"] != plan_sha):
                raise AdmissionError("ADMISSION_OWNER_PLAN_IDENTITY_MISMATCH")
            # No two independently active Episodes can compete for the same GPU Worker.
            for row in db.execute(
                "SELECT audit_id, resource_id FROM audit_events WHERE action=?",
                (_ADMIT,),
            ).fetchall():
                if row["resource_id"] != episode_id and not db.execute(
                    "SELECT 1 FROM audit_events WHERE action=? AND resource_id=?",
                    (_REVOKE, row["audit_id"]),
                ).fetchone():
                    raise AdmissionError("ADMISSION_OTHER_EPISODE_ALREADY_ACTIVE")
            existing = db.execute(
                "SELECT audit_id FROM audit_events WHERE action=? AND resource_id=?",
                (_ADMIT, episode_id),
            ).fetchall()
            if existing:
                if len(existing) != 1:
                    raise AdmissionError("ADMISSION_DUPLICATE_AUDIT")
                row, details = _event(db, existing[0]["audit_id"], _ADMIT)
                if db.execute(
                    "SELECT 1 FROM audit_events WHERE action=? AND resource_id=?",
                    (_REVOKE, row["audit_id"]),
                ).fetchone():
                    raise AdmissionError("ADMISSION_REVOKED_CANNOT_REUSE")
                if row["actor_id"] != principal.actor_id or details != evidence:
                    raise AdmissionError("ADMISSION_CONFLICT")
                return self._receipt(row["audit_id"], evidence, True)
            grant_id = self.audit.append(
                connection=db, trace_id=trace_id,
                actor_type="owner_principal", actor_id=principal.actor_id,
                action=_ADMIT, resource_type="episode", resource_id=episode_id,
                decision="SCOPED_ONE_EPISODE", reason_code=None,
                details=evidence,
            )
        return self._receipt(grant_id, evidence, False)

    @staticmethod
    def _receipt(audit_id: str, evidence: dict, repeated: bool) -> dict:
        return {
            "status": "OWNER_ADMITTED_ONE_FROZEN_EPISODE",
            "admission_id": audit_id,
            "episode_id": evidence["episode_id"],
            "frozen_plan_sha256": evidence["frozen_plan_sha256"],
            "worker_id": evidence["worker_id"],
            "already_admitted": repeated,
            "lease_requires_worker_hmac": True,
            "local_gpu_submitted": False,
            "gpu_authorized_for_exact_episode": True,
        }

    def revoke(self, episode_id: str, admission_id: str,
               principal: OwnerPrincipal, trace_id: str) -> dict:
        with self.database.transaction() as db:
            plan = MasterEvidenceService._frozen(db, episode_id)
            require_owner_scope(principal, plan["subject_key"], permission="production.admit")
            if principal.actor_id != plan["owner_actor_id"]:
                raise AdmissionError("ADMISSION_REVOKE_OWNER_MISMATCH")
            row, _ = _event(db, admission_id, _ADMIT)
            if row["resource_id"] != episode_id or row["actor_id"] != principal.actor_id:
                raise AdmissionError("ADMISSION_REVOKE_SCOPE")
            if not db.execute(
                "SELECT 1 FROM audit_events WHERE action=? AND resource_id=?",
                (_REVOKE, admission_id),
            ).fetchone():
                self.audit.append(
                    connection=db, trace_id=trace_id, actor_type="owner_principal",
                    actor_id=principal.actor_id, action=_REVOKE,
                    resource_type="episode.scoped_gpu_admission",
                    resource_id=admission_id, decision="REVOKED",
                    reason_code="OWNER_REVOKED_GPU_ADMISSION",
                    details={"episode_id": episode_id},
                )
        return {"status": "REVOKED", "admission_id": admission_id, "can_lease": False}

    def _eligible(self, db, episode_id: str) -> list:
        """Only frozen original tasks or Core-created QC checks of those exact tasks."""
        all_rows = db.execute(
            "SELECT * FROM tasks WHERE json_extract(payload_json, '$.episode_id')=? "
            "ORDER BY rowid",
            (episode_id,),
        ).fetchall()
        original = {
            row["task_id"]: row for row in all_rows
            if row["task_type"] in ("gen.keyframe", "gen.video", "gen.foley")
        }
        result = []
        for row in all_rows:
            task_type = row["task_type"]
            if task_type not in TASK_RUNNERS or row["resource_tag"] != GPU_TAG:
                raise AdmissionError("ADMISSION_UNPLANNED_TASK_IN_EPISODE")
            payload = json.loads(row["payload_json"])
            if payload.get("runner") != TASK_RUNNERS[task_type]:
                raise AdmissionError("ADMISSION_RUNNER_CHANGED")
            if task_type == "qc.check":
                jobs = payload.get("jobs", {})
                parent = original.get(jobs.get("source_task_id"))
                if (parent is None or parent["task_type"] not in ("gen.keyframe", "gen.video")
                        or row["parent_task_id"] != parent["task_id"]
                        or jobs.get("source_type") != parent["task_type"]):
                    raise AdmissionError("ADMISSION_UNTRUSTED_QC_TASK")
            result.append(row)
        return result

    def _candidate(self, db, episode_id: str, worker_id: str,
                   resume_id: str | None) -> dict | None:
        now = datetime.now(UTC).isoformat()
        allowed = self._eligible(db, episode_id)
        for row in allowed:
            if resume_id is not None and row["task_id"] != resume_id:
                continue
            status = row["status"]
            if status == TaskStatus.RUNNING.value:
                # 只允许带有相同 task_id 的旧 Journal 恢复；无 Journal 不重投。
                if resume_id != row["task_id"]:
                    continue
                if (row["lease_owner"] != worker_id
                        or row["lease_expires_at"] is None):
                    continue
                # Old pre-admission journals must never become eligible retroactively.
                grants = db.execute(
                    "SELECT details_redacted_json FROM audit_events WHERE action=? "
                    "AND resource_id=? ORDER BY rowid DESC",
                    (_LEASE, row["task_id"]),
                ).fetchall()
                if not grants:
                    continue
                last = json.loads(grants[0]["details_redacted_json"])
                if (last.get("worker_id") != worker_id
                        or last.get("attempt_count") != row["attempt_count"]):
                    continue
                if row["lease_expires_at"] < now:
                    return {"task_id": row["task_id"], "status": "Expired"}
                return {"task_id": row["task_id"], "status": status}
            if status not in (TaskStatus.QUEUED.value, TaskStatus.RETRYING.value):
                continue
            if db.execute(
                "SELECT 1 FROM task_dependencies dep "
                "JOIN tasks parent ON dep.depends_on_task_id=parent.task_id "
                "WHERE dep.task_id=? AND parent.status <> 'Completed' LIMIT 1",
                (row["task_id"],),
            ).fetchone():
                continue
            return {"task_id": row["task_id"], "status": status}
        return None

    def next_lease(self, body: ExecutorLease) -> dict | None:
        if body.worker_id != self.services.settings.worker_attestation_id:
            raise AdmissionError("ADMISSION_WORKER_ID_WRONG")
        if GPU_TAG not in body.resource_tags:
            return None
        with self.database.transaction() as db:
            rows = db.execute(
                "SELECT resource_id FROM audit_events WHERE action=? ORDER BY rowid",
                (_ADMIT,),
            ).fetchall()
            active = []
            for row in rows:
                episode_id = row["resource_id"]
                try:
                    evidence, _, grant_id = self._active(db, episode_id)
                except (AdmissionError, MasterEvidenceError, WorkerProofError,
                        OwnerAuthFailure, ValueError, KeyError):
                    continue
                active.append((evidence, grant_id))
            if len(active) != 1:
                return None
            evidence, grant_id = active[0]
            choice = self._candidate(
                db, evidence["episode_id"], body.worker_id, body.resume_task_id,
            )
            return {
                **evidence,
                "admission_id": grant_id,
                "task_id": choice["task_id"],
                "task_status": choice["status"],
            } if choice is not None else None

    def lease_task(self, body: ExecutorLease, target: dict,
                   trace_id: str):
        # Work exclusively inside the existing ExecutorService QueueRepository transaction.
        with self.database.transaction() as db:
            evidence, _, admission_id = self._active(db, target["episode_id"])
            if (admission_id != target["admission_id"]
                    or body.worker_id != evidence["worker_id"]
                    or evidence["frozen_plan_sha256"] != target["frozen_plan_sha256"]):
                raise AdmissionError("ADMISSION_REVOKED_OR_CHANGED_BEFORE_LEASE")
            choice = self._candidate(
                db, evidence["episode_id"], body.worker_id, body.resume_task_id,
            )
            if choice is None or choice["task_id"] != target["task_id"]:
                raise AdmissionError("ADMISSION_SELECTED_TASK_CHANGED")
            task_id = choice["task_id"]
            if choice["status"] == TaskStatus.RUNNING.value:
                row = db.execute(
                    "SELECT * FROM tasks WHERE task_id=?", (task_id,),
                ).fetchone()
                return self.services.queue._row_to_record(row)
            if choice["status"] == TaskStatus.RETRYING.value:
                self.services.queue.transition_in_transaction(
                    db, task_id=task_id, target=TaskStatus.QUEUED,
                    reason="scoped_executor_retry", trace_id=trace_id,
                )
            leased = self.services.queue.lease_next(
                body.worker_id, body.lease_seconds, trace_id=trace_id,
                resource_tags=(GPU_TAG,), task_types=tuple(TASK_RUNNERS),
                task_id=task_id, connection=db,
            )
            if leased is None:
                raise AdmissionError("ADMISSION_TASK_NOT_LEASABLE")
            db.execute(
                "INSERT INTO executor_leases(task_id, lease_seconds) VALUES(?, ?) "
                "ON CONFLICT(task_id) DO UPDATE SET lease_seconds=excluded.lease_seconds",
                (task_id, body.lease_seconds),
            )
            self.services.executor._audit(
                db, trace_id, "lease", task_id, body.worker_id,
            )
            self.audit.append(
                connection=db, trace_id=trace_id, actor_type="worker_hmac",
                actor_id=body.worker_id, action=_LEASE, resource_type="task",
                resource_id=task_id, decision="EXACT_FROZEN_TASK_ONLY",
                reason_code=None,
                details={
                    "episode_id": target["episode_id"],
                    "admission_id": admission_id,
                    "frozen_plan_sha256": evidence["frozen_plan_sha256"],
                    "worker_id": body.worker_id,
                    "attempt_count": leased.attempt_count,
                },
            )
            return leased

    def heartbeat_allowed(self, task_id: str, worker_id: str, attempt_count: int | None) -> bool:
        with self.database.transaction() as db:
            row = db.execute(
                "SELECT status, attempt_count, lease_owner, payload_json FROM tasks "
                "WHERE task_id=?", (task_id,),
            ).fetchone()
            if row is None or row["lease_owner"] != worker_id:
                return False
            if attempt_count is not None and row["attempt_count"] != attempt_count:
                return False
            episode_id = json.loads(row["payload_json"]).get("episode_id")
            if not episode_id:
                return False
            try:
                evidence, _, admission_id = self._active(db, episode_id)
            except (AdmissionError, MasterEvidenceError, WorkerProofError,
                    OwnerAuthFailure, ValueError, KeyError):
                return False
            grant_rows = db.execute(
                "SELECT details_redacted_json FROM audit_events WHERE action=? "
                "AND resource_id=? ORDER BY rowid DESC", (_LEASE, task_id),
            ).fetchall()
            if not grant_rows:
                return False
            last = json.loads(grant_rows[0]["details_redacted_json"])
            return (
                row["status"] == TaskStatus.RUNNING.value
                and last.get("attempt_count") == row["attempt_count"]
                and last.get("admission_id") == admission_id
                and last.get("worker_id") == worker_id
                and last.get("frozen_plan_sha256") == evidence["frozen_plan_sha256"]
            )


class LeaseChallengeRegistry:
    """Short-lived, one-use HMAC challenge; never records another production queue."""

    def __init__(self, services) -> None:
        self.services = services
        self.admission = ScopedProductionAdmission(services)
        self._lock = threading.RLock()
        self._pending: dict | None = None

    def issue(self, body: ExecutorLease) -> dict | None:
        with self._lock:
            candidate = self.admission.next_lease(body)
            if candidate is not None and candidate["task_status"] == "Expired":
                # 仅恢复已经证明是本 Episode + 本 Worker 的过期旧租约。
                self.services.queue.recover_expired_leases(
                    resource_tags=(GPU_TAG,), task_types=tuple(TASK_RUNNERS),
                    task_id=candidate["task_id"],
                )
                candidate = self.admission.next_lease(body)
            if candidate is None or candidate["task_status"] == "Expired":
                return None
            nonce = secrets.token_urlsafe(32)
            message = {
                "contract": _LEASE_CONTRACT,
                "nonce": nonce,
                "worker_id": body.worker_id,
                "episode_id": candidate["episode_id"],
                "task_id": candidate["task_id"],
                "frozen_plan_sha256": candidate["frozen_plan_sha256"],
                "resource_tags": sorted(body.resource_tags),
                "lease_seconds": body.lease_seconds,
                "resume_task_id": body.resume_task_id,
            }
            self._pending = {
                "message": message,
                "candidate": candidate,
                "expires": time.monotonic() + 60,
            }
            return {
                **message,
                "lease_challenge": True,
                "gpu_authorized_for_exact_episode": True,
            }

    def consume(self, body: ExecutorLease, nonce: str | None, signature: str | None,
                trace_id: str):
        with self._lock:
            pending = self._pending
            self._pending = None
            if (pending is None or time.monotonic() >= pending["expires"]
                    or not isinstance(nonce, str) or
                    not isinstance(signature, str)):
                raise AdmissionError("ADMISSION_LEASE_CHALLENGE_EXPIRED")
            message = pending["message"]
            if (nonce != message["nonce"]
                    or body.worker_id != message["worker_id"]
                    or body.lease_seconds != message["lease_seconds"]
                    or body.resume_task_id != message["resume_task_id"]
                    or sorted(body.resource_tags) != message["resource_tags"]):
                raise AdmissionError("ADMISSION_LEASE_BODY_CHANGED")
            key = self.services.settings.worker_attestation_key
            if not key:
                raise AdmissionError("ADMISSION_WORKER_SIGNING_KEY_DISABLED")
            expected = hmac.new(
                key.encode("ascii"), _hash_message(message), hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise AdmissionError("ADMISSION_WORKER_HMAC_INVALID")
            return self.admission.lease_task(body, pending["candidate"], trace_id)
