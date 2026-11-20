"""连接 Mac Core 与现有 Windows 文件队列。Python 3.11+，仅依赖 requests。"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import hmac
import json
import logging
import os
import re
import stat
import shutil
import signal
import subprocess
import sys
import time
import tomllib
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import requests

if __package__:
    from .media_probe import probe_command, probe_json
    from .production_qc import check_candidates
else:
    from media_probe import probe_command, probe_json
    from production_qc import check_candidates

POLL_SECONDS = 5
HEARTBEAT_SECONDS = 20
THUMBNAIL_LIMIT = 300 * 1024
TERMINAL = {"Completed", "Failed", "Cancelled", "Archived"}
RUNNERS = {
    "gen.keyframe": "run_qwen_edit.py",
    "gen.video": "run_ltx_flf.py",
    "gen.foley": "run_foley.py",
    "qc.check": "qc.check",
    "edit.assemble": "edit.assemble",
}
KINDS = {
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
    ".mp4": "video",
    ".mov": "video",
    ".mkv": "video",
    ".webm": "video",
    ".wav": "audio",
    ".flac": "audio",
    ".mp3": "audio",
    ".m4a": "audio",
}
LOG = logging.getLogger("executor_bridge")
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,100}")
STAGED_IMAGE = re.compile(r"([0-9a-f]{64})\.(png|jpg|webp)")


class JobError(ValueError):
    """任务或本地产物需要操作员处理。"""


@dataclass(frozen=True)
class BridgeConfig:
    core_url: str
    worker_id: str
    root: Path
    resource_tags: tuple[str, ...] = ("gpu-5070ti",)
    lease_seconds: int = 90


def atomic_json(path: Path, payload: dict):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, allow_nan=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


class Bridge:
    def __init__(self, config: BridgeConfig, session: requests.Session):
        self.config = config
        self.session = session
        self.root = config.root.resolve()
        self.board = self.root / "17_静态首帧板V2"
        self.queue = self.root / "_queue"
        self.state_dir = self.queue / "executor_bridge"
        for folder in (
            self.board,
            self.state_dir,
            *(
                self.queue / name
                for name in (
                    "inbox",
                    "running",
                    "done",
                    "failed",
                )
            ),
        ):
            folder.mkdir(parents=True, exist_ok=True)
        self.journal = self.state_dir / f"{config.worker_id}.json"
        self.pause_marker = self.state_dir / f"{config.worker_id}.pause-new.json"
        self.next_heartbeat = 0.0
        self.next_worker_proof_at = 0.0  # 独立 Worker 证据最多每 60 秒 CPU 复核一次。

    def _request(self, method: str, route: str, **kwargs):
        return self.session.request(
            method,
            f"{self.config.core_url.rstrip('/')}/api/v1{route}",
            timeout=(4, 8),
            allow_redirects=False,
            **kwargs,
        )

    def _lease(self, resume_task_id=None):
        body = {
            "worker_id": self.config.worker_id,
            "resource_tags": list(self.config.resource_tags),
            "lease_seconds": self.config.lease_seconds,
            "resume_task_id": resume_task_id,
        }
        signing_key = os.environ.get("PICOTOO_WORKER_ATTEST_KEY", "")
        signed_headers = {}
        if signing_key and re.fullmatch(r"[A-Za-z0-9_-]{43,256}", signing_key):
            challenge = self._request(
                "POST", "/studio/production-admission/lease-challenge", json=body,
            )
            if challenge.status_code == 200:
                offered = challenge.json()
                if (offered.get("contract") != "picotoo.scoped-worker-lease.v1"
                        or offered.get("worker_id") != body["worker_id"]
                        or offered.get("lease_seconds") != body["lease_seconds"]
                        or offered.get("resume_task_id") != resume_task_id
                        or sorted(offered.get("resource_tags", []))
                        != sorted(body["resource_tags"])
                        or not re.fullmatch(
                            r"[0-9a-f]{64}", str(offered.get("frozen_plan_sha256", ""))
                        )
                        or not IDENTIFIER.fullmatch(str(offered.get("task_id", "")))
                        or not IDENTIFIER.fullmatch(str(offered.get("episode_id", "")))):
                    raise JobError("Core GPU 准入挑战与本机 Worker 不一致。")
                keys = (
                    "contract", "nonce", "worker_id", "episode_id", "task_id",
                    "frozen_plan_sha256", "resource_tags", "lease_seconds",
                    "resume_task_id",
                )
                message = {k: offered[k] for k in keys}
                sha = hashlib.sha256(json.dumps(
                    message, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"), allow_nan=False,
                ).encode("utf-8")).hexdigest()
                signed_headers = {
                    "X-Picotoo-Admission-Nonce": offered["nonce"],
                    "X-Picotoo-Admission-HMAC": hmac.new(
                        signing_key.encode("ascii"), sha.encode("ascii"),
                        hashlib.sha256,
                    ).hexdigest(),
                }
            elif challenge.status_code != 204:
                # Proof challenge failed: never fall back to unsigned GPU lease.
                raise JobError("Core 受控 GPU 租约预检不可用。")
        # Owner HOLD requires a one-use signed nonce; old unconfigured Core still
        # preserves its legacy behavior. No new local GPU job is written here.
        response = self._request(
            "POST", "/executors/lease", json=body,
            **({"headers": signed_headers} if signed_headers else {}),
        )
        if response.status_code == 204:
            return None
        response.raise_for_status()
        return response.json()

    def _maybe_report_worker_proof(self) -> None:
        """Prove real staged bytes with distinct HMAC; never bypass a held lease."""
        secret = os.environ.get("PICOTOO_WORKER_ATTEST_KEY", "")
        if not secret:
            return  # 默认关闭，不改变旧 Worker 的任何网络或 GPU 行为。
        now = time.monotonic()
        if now < self.next_worker_proof_at:
            return
        self.next_worker_proof_at = now + 60
        if (len(secret) < 43 or len(secret) > 256 or
                not re.fullmatch(r"[A-Za-z0-9_-]+", secret)):
            LOG.warning("WORKER_PROOF_SECRET_INVALID")
            return
        try:
            response = self._request(
                "POST", "/studio/worker-proof/claim",
                json={"worker_id": self.config.worker_id},
            )
            if response.status_code == 204:
                return
            if response.status_code != 200:
                LOG.warning("WORKER_PROOF_CLAIM_UNAVAILABLE code=%d", response.status_code)
                return
            challenge = response.json()
            if (challenge.get("worker_id") != self.config.worker_id
                    or challenge.get("can_lease") is not False
                    or challenge.get("gpu_authorized") is not False):
                raise JobError("Worker 证据挑战不可携带 GPU 放行。")
            bindings = challenge.get("bindings")
            if not isinstance(bindings, list) or not 1 <= len(bindings) <= 960:
                raise JobError("Worker 证据缺少镜头绑定。")
            verified = set()
            for entry in bindings:
                if not isinstance(entry, dict) or set(entry) != {
                    "shot_id", "role", "asset_ref", "managed_sha256"
                }:
                    raise JobError("Worker 证据的镜头绑定结构无效。")
                digest = entry["managed_sha256"]
                if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                    raise JobError("Worker 证据的图片 SHA 无效。")
                if entry["role"] not in ("first", "last"):
                    raise JobError("Worker 证据使用了未知首末帧角色。")
                identity = (entry["shot_id"], entry["role"], entry["asset_ref"])
                if identity in verified:
                    raise JobError("Worker 证据的镜头引用重复。")
                verified.add(identity)
                root = self.state_dir / "staged_references"
                matches = [
                    root / f"{digest}{suffix}"
                    for suffix in (".png", ".jpg", ".webp")
                    if (root / f"{digest}{suffix}").exists()
                    or (root / f"{digest}{suffix}").is_symlink()
                ]
                if len(matches) != 1:
                    raise JobError("Worker 没有唯一的本地 SHA 图片。")
                # 与正式 GPU 提交前采用完全相同的安全文件校验函数。
                self._verify_staged_reference(
                    f"../_queue/executor_bridge/staged_references/{matches[0].name}"
                )
            canonical = json.dumps(
                bindings, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), allow_nan=False,
            ).encode("utf-8")
            bindings_sha = hashlib.sha256(canonical).hexdigest()
            if bindings_sha != challenge.get("bindings_sha256"):
                raise JobError("Worker 实际核验的绑定集合与 Core 挑战不符。")
            keys = (
                "nonce", "worker_id", "episode_id", "frozen_plan_sha256",
                "source_bindings_sha256", "bindings_sha256",
            )
            if any(not isinstance(challenge.get(k), str) for k in keys):
                raise JobError("Worker 证据挑战缺少冻结 Plan 身份。")
            msg = {"contract": "picotoo.worker-local-sha-proof.v1",
                   **{key: challenge[key] for key in keys}}
            canonical_message = json.dumps(
                msg, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), allow_nan=False,
            ).encode("utf-8")
            payload = {
                **msg,
                "signature": hmac.new(
                    secret.encode("ascii"), hashlib.sha256(canonical_message).hexdigest().encode("ascii"),
                    hashlib.sha256,
                ).hexdigest(),
            }
            reply = self._request(
                "POST", "/studio/worker-proof/submit", json=payload,
            )
            if reply.status_code != 200:
                LOG.warning("WORKER_PROOF_REPORT_REJECTED code=%d", reply.status_code)
                return
            receipt = reply.json()
            if (receipt.get("gpu_authorized") is not False
                    or receipt.get("can_lease") is not False):
                raise JobError("Worker SHA 证明不能赋予 GPU 权限。")
            LOG.info("WORKER_SHA_REPORTED_HELD episode=%s", msg["episode_id"])
        except (JobError, requests.RequestException, ValueError, KeyError) as error:
            # 不改变现有 Journal 或租约状态，错误只需等待新的 CPU challenge。
            LOG.warning("WORKER_PROOF_NO_GPU: %s", str(error)[:200])

    def _new_state(self, task):
        task_id = task["task_id"]
        if not IDENTIFIER.fullmatch(task_id):
            raise JobError("Mac Core 返回了无效的 task_id。")
        state = {"task": task, "stem": f"{time.time_ns():020d}_{task_id}"}
        atomic_json(self.journal, state)
        return state

    @staticmethod
    def _route(state):
        return f"/tasks/{state['task']['task_id']}"

    def _owner(self, state):
        return {"worker_id": self.config.worker_id, "attempt_count": state["task"]["attempt_count"]}

    def _heartbeat(self, state, progress=0.5, *, force=False):
        if not force and time.monotonic() < self.next_heartbeat:
            return True
        response = self._request(
            "POST",
            self._route(state) + "/heartbeat",
            json={
                **self._owner(state),
                "progress": progress,
                "message": "等待本地执行" if progress < 0.9 else "登记本地产物",
            },
        )
        if response.status_code == 409:
            return False
        response.raise_for_status()
        self.next_heartbeat = time.monotonic() + HEARTBEAT_SECONDS
        return True

    def _resume(self, state):
        task_id = state["task"]["task_id"]
        current = self._lease(task_id)
        if current is None:
            response = self._request("GET", self._route(state))
            response.raise_for_status()
            if response.json()["status"] in TERMINAL:
                # 保留本地记录，便于人工核对过期或取消后的产物。
                self.journal.replace(self.state_dir / f"{state['stem']}.closed.json")
            return None
        if current["attempt_count"] != state["task"]["attempt_count"]:
            if "error" in state.get("report", {}):
                return self._new_state(current)
            state["task"] = current
            state.pop("report_ready", None)
            atomic_json(self.journal, state)
        self.next_heartbeat = 0
        return state

    def _new_tasks_paused(self) -> bool:
        # Windows 本地暂停标记仅约束当前 Worker，绝不等同于 Core 全局 GPU HOLD。
        return self.pause_marker.exists() or self.pause_marker.is_symlink()

    def step(self):
        if self.journal.exists():
            state = json.loads(self.journal.read_text(encoding="utf-8"))
        else:
            # 暂停后不再领取新任务；已有 Journal 的恢复仍优先进行。
            if self._new_tasks_paused():
                return
            task = self._lease()
            if task is None:
                # HOLD 下闲置时只做 SHA 证明；不会向本地 inbox 发新 GPU 作业。
                self._maybe_report_worker_proof()
                return
            state = self._new_state(task)
            self.next_heartbeat = 0

        if "report" in state:
            if not self._send_report(state):
                self._resume(state)
            return
        if not self._heartbeat(state):
            state = self._resume(state)
            if state is None or not self._heartbeat(state):
                return
        # 如果已领租约但尚未送到本地队列，暂停时先保持 Journal 与心跳。
        # 旧的 submitted 任务仍继续收回执，避免抛弃已经运行的 GPU 作业。
        if self._new_tasks_paused() and not state.get("submitted"):
            return
        try:
            result = self._work(state)
            if result is None:
                return
            self._stage_report(state, result)
        except JobError as exc:
            state["report"] = {"error": str(exc)[:2000], "retryable": False}
        atomic_json(self.journal, state)
        if not self._send_report(state):
            self._resume(state)

    def _safe_path(self, raw: str, base: Path | None = None) -> Path:
        path = ((base or self.root) / raw).resolve()
        if not path.is_relative_to(self.root):
            raise JobError("任务引用的文件超出项目目录。")
        return path

    def _parent(self, task):
        if not task.get("parent_task_id"):
            return []
        response = self._request("GET", f"/tasks/{task['task_id']}/artifacts")
        response.raise_for_status()
        upstream = response.json().get("upstream_task_id")
        if upstream is None:
            return []
        response = self._request("GET", f"/tasks/{upstream}/artifacts")
        response.raise_for_status()
        artifacts = response.json()["artifacts"]
        reviewed = task["payload"]["jobs"].get("reviewed_inputs")
        if reviewed is None:
            return artifacts
        if not isinstance(reviewed, list) or not reviewed:
            raise JobError("人工放行清单为空或无效。")
        by_id = {item["artifact_id"]: item for item in artifacts}
        checked = []
        for record in reviewed:
            item = by_id.get(record.get("artifact_id")) if isinstance(record, dict) else None
            if item is None or any(
                field not in record or record[field] != item[field]
                for field in ("sha256", "path", "kind", "take")
            ):
                raise JobError("人工放行清单与上游登记不一致。")
            path = self._safe_path(item["path"])
            if not path.is_file() or self._hash(path, {"task": task})[0] != item["sha256"]:
                raise JobError("人工放行素材的本机文件已改变。")
            checked.append(item)
        return checked

    def _verify_staged_reference(self, raw: str) -> None:
        """在生成本地 Worker inbox 前，重新哈希每个已同步的首帧文件。

        Stage receipt 不是永久通行证；仅用真实 SHA 命名的图像才被认为
        是同步资产，普通 legacy 本地 refs 保持原行为。
        """
        staged = self.state_dir / "staged_references"
        lexical = Path(os.path.abspath(self.board / raw))
        resolved = self._safe_path(raw, self.board)
        if not (lexical.is_relative_to(staged) or resolved.is_relative_to(staged)):
            return
        if (
            lexical.parent != staged
            or resolved != lexical
            or staged.is_symlink()
            or self.state_dir.is_symlink()
            or self.queue.is_symlink()
            or lexical.is_symlink()
        ):
            raise JobError("首帧暂存目录或文件为不可信的符号链接。")
        match = STAGED_IMAGE.fullmatch(lexical.name)
        if match is None:
            raise JobError("已同步首帧未使用合法 SHA-256 文件名。")
        expected, extension = match.groups()
        try:
            fd = os.open(lexical, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "rb") as handle:
                metadata = os.fstat(handle.fileno())
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 64 * 1024 * 1024:
                    raise JobError("已同步首帧不是有效的受限普通文件。")
                header = handle.read(16)
                valid_image = (
                    extension == "png" and header.startswith(b"\x89PNG\r\n\x1a\n")
                    or extension == "jpg" and header.startswith(b"\xff\xd8\xff")
                    or extension == "webp"
                    and header[:4] == b"RIFF" and header[8:12] == b"WEBP"
                )
                if not valid_image:
                    raise JobError("已同步首帧图片格式不符合 SHA 文件名。")
                sha = hashlib.sha256()
                sha.update(header)
                length = len(header)
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    length += len(chunk)
                    if length > 64 * 1024 * 1024:
                        raise JobError("已同步首帧超过本地体积上限。")
                    sha.update(chunk)
                if (
                    length != metadata.st_size
                    or os.fstat(handle.fileno()).st_size != length
                    or sha.hexdigest() != expected
                ):
                    raise JobError("已同步首帧的本地 SHA 已改变，禁止提交 GPU 作业。")
        except OSError as error:
            raise JobError("已同步首帧无法安全重新校验。") from error


    def _bind_managed_frame_refs(self, task: dict, jobs: dict) -> None:
        """Map Core's content-addressed StoryPack IDs to verified Windows images.

        The manifest is a *data* contract, not an Owner approval or lease.
        It must be inserted by a future independently authorized, immutable
        Core production Plan. This method cannot grant GPU permission.
        """
        has_manifest = "frame_source_manifest" in jobs
        has_digest = "source_bindings_sha256" in jobs
        if not has_manifest and not has_digest:
            return
        if not (has_manifest and has_digest) or task.get("task_type") != "gen.keyframe":
            raise JobError("受管理首帧绑定缺少完整的冻结源清单。")
        manifest = jobs.pop("frame_source_manifest")
        claimed_sha = jobs.pop("source_bindings_sha256")
        if (
            not isinstance(manifest, dict)
            or set(manifest) != {
                "contract", "storypack_sha256", "owner_subject_sha256", "bindings"
            }
            or manifest.get("contract") != "picotoo.frame-source-manifest.v1"
            or not isinstance(claimed_sha, str)
            or not re.fullmatch(r"[0-9a-f]{64}", claimed_sha)
            or any(
                not isinstance(manifest.get(field), str)
                or not re.fullmatch(r"[0-9a-f]{64}", manifest[field])
                for field in ("storypack_sha256", "owner_subject_sha256")
            )
        ):
            raise JobError("受管理首帧源清单格式无效。")
        canonical = json.dumps(
            manifest, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        if len(canonical) > 128 * 1024:
            raise JobError("受管理首帧清单超过已支持的大小。")
        if hashlib.sha256(canonical).hexdigest() != claimed_sha:
            raise JobError("受管理首帧清单与冻结 SHA 不一致。")

        bindings = manifest["bindings"]
        if not isinstance(bindings, list) or not 1 <= len(bindings) <= 960:
            raise JobError("受管理首帧绑定数量无效。")
        declared = {}
        for binding in bindings:
            if (
                not isinstance(binding, dict)
                or set(binding) != {"shot_id", "role", "asset_ref", "managed_sha256"}
            ):
                raise JobError("受管理首帧条目结构无效。")
            shot = binding["shot_id"]
            role = binding["role"]
            ref = binding["asset_ref"]
            digest = binding["managed_sha256"]
            if (
                not isinstance(shot, str)
                or not IDENTIFIER.fullmatch(shot)
                or role not in ("first", "last")
                or not isinstance(ref, str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{2,99}", ref)
                or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or (shot, role, ref) in declared
            ):
                raise JobError("受管理首帧条目不可信或重复。")
            declared[(shot, role, ref)] = digest

        shot_id = task["payload"].get("shot_id")
        if not isinstance(shot_id, str) or not IDENTIFIER.fullmatch(shot_id):
            raise JobError("受管理首帧没有有效镜头身份。")
        entries = jobs.get("jobs")
        if not isinstance(entries, list) or not 1 <= len(entries) <= 2:
            raise JobError("受管理首帧作业列表无效。")
        required = {
            (role, ref)
            for (shot, role, ref) in declared
            if shot == shot_id
        }
        actual = set()
        seen_roles = set()
        staged_dir = self.state_dir / "staged_references"
        for entry in entries:
            if not isinstance(entry, dict):
                raise JobError("受管理首帧作业对象无效。")
            job_id = entry.get("id")
            if job_id not in (f"{shot_id}_first", f"{shot_id}_last"):
                raise JobError("首帧绑定与当前 shot_id、role 不一致。")
            role = job_id.removeprefix(f"{shot_id}_")
            if role in seen_roles:
                raise JobError("受管理首帧存在重复的镜头角色。")
            seen_roles.add(role)
            refs = entry.get("refs")
            if not isinstance(refs, list) or not refs or len(refs) > 32:
                raise JobError("受管理首帧引用列表无效。")
            rewritten = []
            for ref in refs:
                if (
                    not isinstance(ref, str)
                    or (role, ref) in actual
                    or (shot_id, role, ref) not in declared
                ):
                    raise JobError("受管理首帧引用缺失、重复或不属于本镜头。")
                actual.add((role, ref))
                digest = declared[(shot_id, role, ref)]
                matches = [
                    staged_dir / f"{digest}{extension}"
                    for extension in (".png", ".jpg", ".webp")
                    if (staged_dir / f"{digest}{extension}").exists()
                    or (staged_dir / f"{digest}{extension}").is_symlink()
                ]
                if len(matches) != 1:
                    raise JobError("Windows 缺少唯一且已验证的首帧 SHA 图片。")
                relative = (
                    f"../_queue/executor_bridge/staged_references/{matches[0].name}"
                )
                # 再次重读真实字节，拒绝被篡改、软链接或格式错误的图像。
                self._verify_staged_reference(relative)
                rewritten.append(relative)
            entry["refs"] = rewritten
        if actual != required:
            raise JobError("本镜头首帧引用与冻结 Mac 清单不完全一致。")

    def _jobs(self, state):
        task = state["task"]
        jobs = deepcopy(task["payload"]["jobs"])
        # Mac Core 原始 refs 是资产 ID，不是 Windows 文件路径。
        # 仅当 Core 明确下发绑定 SHA 时才转换；不能猜测或搜索同名图片。
        self._bind_managed_frame_refs(task, jobs)
        if jobs.get("out") == "$bridge.output":
            jobs["out"] = f"../_queue/executor_bridge/outputs/{state['stem']}"
        if "out" in jobs:
            if not isinstance(jobs["out"], str):
                raise JobError("jobs.out 须为项目内的目录路径。")
            self._safe_path(jobs["out"], self.board)
        parent = None
        expanded = []
        checked_refs: set[str] = set()
        entries = jobs.get("jobs", [])
        if not isinstance(entries, list) or any(not isinstance(job, dict) for job in entries):
            raise JobError("jobs.jobs 须为作业对象数组。")
        for job in entries:
            if not IDENTIFIER.fullmatch(str(job.get("id", ""))):
                raise JobError("jobs 中的 id 无效。")
            refs = job.get("refs", [])
            if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
                raise JobError("jobs.jobs 的 refs 须为路径数组。")
            for ref in [*refs, job.get("mask")]:
                if ref:
                    if not isinstance(ref, str):
                        raise JobError("jobs.jobs 的 mask 须为路径。")
                    self._safe_path(ref, self.board)
                    if ref not in checked_refs:
                        self._verify_staged_reference(ref)
                        checked_refs.add(ref)
            for field in ("first", "last", "video"):
                value = job.get(field)
                if not value:
                    continue
                if not isinstance(value, str):
                    raise JobError(f"jobs.jobs 的 {field} 须为路径。")
                if value.startswith("$parent."):
                    if parent is None:
                        parent = self._parent(task)
                    matches = [
                        item
                        for item in parent
                        if (
                            field == "video"
                            and item["kind"] == "video"
                            or field != "video"
                            and item["kind"] == "image"
                            and (
                                Path(item["path"]).stem
                                == f"{task['payload']['shot_id']}_{field}_v{item['take']}"
                                if jobs.get("reviewed_inputs")
                                else f"_{field}_" in Path(item["path"]).stem
                            )
                        )
                    ]
                    if not matches:
                        raise JobError(f"上游任务没有可用的 {field} 产物。")
                    matches.sort(key=lambda item: (item["decision"] != "pick", item["take"]))
                    if field == "video":
                        for i, item in enumerate(matches, 1):
                            state.setdefault("foley_sources", {})[f"{job['id']}_{i}"] = item[
                                "sha256"
                            ]
                            expanded.append(
                                {
                                    **job,
                                    "id": f"{job['id']}_{i}",
                                    "video": str(self._safe_path(item["path"])),
                                }
                            )
                        break
                    job[field] = str(self._safe_path(matches[0]["path"]))
                else:
                    self._safe_path(value, self.board)
            else:
                expanded.append(job)
        if "jobs" in jobs:
            jobs["jobs"] = expanded
        return jobs

    def _worker_result(self, state):
        for folder in ("done", "failed"):
            receipt = self.queue / folder / f"{state['stem']}.result.json"
            if not receipt.is_file():
                continue
            try:
                result = json.loads(receipt.read_text(encoding="utf-8-sig"))
            except (UnicodeError, json.JSONDecodeError):
                return None  # worker 直接写入文件，等下一次轮询读取完整 JSON。
            result["ok"] = folder == "done" and result.get("ok") is True
            result.setdefault("sheet", str(receipt.with_name(f"{state['stem']}.sheet.jpg")))
            return result
        return None

    def _work(self, state):
        task = state["task"]
        payload = task["payload"]
        runner = RUNNERS.get(task["task_type"])
        if runner is None or runner != payload["runner"]:
            raise JobError("任务与允许的本地 runner 不匹配。")
        if runner == "qc.check":
            candidates = payload["jobs"].get("artifacts")
            return self._qc(state, self._parent(task) if candidates is None else candidates)
        if runner == "edit.assemble":
            return self._assemble(state)
        foley_jobs = payload["jobs"].get("jobs", [])
        if (
            task["task_type"] == "gen.foley"
            and isinstance(foley_jobs, list)
            and foley_jobs
            and isinstance(foley_jobs[0], dict)
            and foley_jobs[0].get("prompt") == ""
            and task.get("parent_task_id")
        ):
            return {
                "ok": True,
                "outputs": [item["path"] for item in self._parent(task) if item["kind"] == "video"],
                "qc": {"foley": "本镜未指定拟音。"},
            }

        result = self._worker_result(state)
        if result is not None:
            return result
        if state.get("submitted"):
            if time.time() - state.get("submitted_at", time.time()) > task["timeout_seconds"]:
                raise JobError("本地文件 worker 未在任务时限内返回回执。")
            return None
        filename = state["stem"] + ".json"
        if not any((self.queue / folder / filename).exists() for folder in ("inbox", "running")):
            # Worker 可能刚从 running 写完回执。
            result = self._worker_result(state)
            if result is not None:
                return result
            jobs_name = f"jobs_{task['task_id']}.json"
            atomic_json(self.board / jobs_name, self._jobs(state))
            if state.get("foley_sources"):
                atomic_json(self.journal, state)
            # 在本地 inbox 真正落盘之前强制刷新 Core 证据和撤销状态。
            # 未经授权/旧 Journal 被禁用时，禁止生成任何新的 GPU 文件任务。
            if os.environ.get("PICOTOO_WORKER_ATTEST_KEY"):
                if not self._heartbeat(state, progress=0.01, force=True):
                    return None
            atomic_json(
                self.queue / "inbox" / filename,
                {
                    "runner": runner,
                    "jobs": jobs_name,
                    "args": payload["args"],
                    "note": task["task_id"],
                },
            )
        state["submitted"] = True
        state["submitted_at"] = time.time()
        atomic_json(self.journal, state)
        return None

    def _hash(self, path: Path, state):
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                if not self._heartbeat(state, 0.9):
                    raise requests.ConnectionError("等待恢复任务租约")
            return digest.hexdigest(), handle.tell()

    def _stage_report(self, state, result):
        if not result["ok"]:
            failures = "\n".join(str(item) for item in result.get("fails", []))
            state["report"] = {
                "error": str(result.get("error") or failures or "Windows worker 执行失败。")[:2000],
                "retryable": bool(result.get("retryable", True)),
            }
            return
        entries = [(name, False) for name in result.get("outputs", [])]
        if state["task"]["task_type"] == "gen.foley":
            paths = {self._safe_path(name) for name, _ in entries}
            for path in sorted(paths):
                if KINDS.get(path.suffix.lower()) != "video":
                    continue
                for suffix in (".flac", ".wav"):
                    audio = self._safe_path(str(path.with_suffix(suffix)))
                    if audio.is_file() and audio not in paths:
                        entries.append((str(audio), False))
        sheet = result.get("sheet")
        if sheet and self._safe_path(sheet).is_file():
            entries.append((sheet, True))
        if len(entries) > 256:
            raise JobError("本地回执的产物超过 256 项，请减少单任务候选数。")
        artifacts, previews = [], []
        for index, (name, is_sheet) in enumerate(entries, 1):
            path = self._safe_path(name)
            kind = "sheet" if is_sheet else KINDS.get(path.suffix.lower())
            if kind is None:
                continue
            if not path.is_file():
                raise JobError(f"找不到 worker 登记的产物：{path.name}。")
            digest, length = self._hash(path, state)
            if kind == "audio" and state.get("foley_sources"):
                source_key = re.sub(r"_v[1-9]\d*$", "", path.stem)
                source = state["foley_sources"].get(source_key)
                if source:
                    result.setdefault("qc", {}).setdefault("foley_by_sha256", {})[digest] = source
            take = re.search(r"_v([1-9]\d*)$", path.stem)
            artifacts.append(
                {
                    "kind": kind,
                    "path": str(path),
                    "sha256": digest,
                    "bytes": length,
                    "shot_id": state["task"]["payload"]["shot_id"],
                    "take": int(take.group(1)) if take else index,
                }
            )
            preview = self._preview(path, kind, state, index)
            if preview:
                previews.append({"path": str(preview), "digest": None if is_sheet else digest})
        if state["task"]["task_type"].startswith("gen.") and not any(
            item["kind"] != "sheet" for item in artifacts
        ):
            state["report"] = {"error": "worker 没有返回可登记的产物。", "retryable": True}
            return
        for digest, path in result.get("qc_previews", {}).items():
            preview = self._preview(self._safe_path(path), "sheet", state, len(previews) + 1)
            if not preview:
                raise JobError("无法生成符合 300 KB 限制的质检报告预览。")
            previews.append({"path": str(preview), "digest": digest})
        state["previews"] = previews
        state["report"] = {
            "artifacts": artifacts,
            "qc": result.get("qc", {}),
            "metrics": {"seconds": result.get("seconds", 0)},
        }

    def _preview(self, path, kind, state, index):
        if kind not in {"image", "sheet", "video"}:
            return None
        if path.suffix.lower() in {".jpg", ".jpeg"} and path.stat().st_size <= THUMBNAIL_LIMIT:
            return path
        if shutil.which("ffmpeg") is None:
            return None
        output = self.state_dir / f"{state['stem']}_{index}.jpg"
        result = self._media(
            state,
            [
                "ffmpeg",
                "-nostdin",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-vf",
                "scale=480:480:force_original_aspect_ratio=decrease",
                "-q:v",
                "5",
                str(output),
            ],
        )
        if result.returncode == 0 and output.is_file() and output.stat().st_size <= THUMBNAIL_LIMIT:
            return output
        LOG.warning("无法制作符合 300 KB 限制的缩略图：%s", path.name)
        return None

    def _send_report(self, state):
        body = {**self._owner(state), **state["report"]}
        action = "fail" if "error" in body else "complete"
        endpoint = self._route(state)
        # 先尝试已提交的最终回报，处理 HTTP 响应在提交后丢失的情况。
        if state.get("report_ready") or not state.get("previews"):
            response = self._request("POST", endpoint + "/" + action, json=body)
            if response.status_code == 409:
                return False
            if response.status_code == 422 and action == "complete":
                state["report"] = {
                    "error": "Mac Core 拒绝不符合契约的本地产物回报。",
                    "retryable": False,
                }
                state["previews"] = []
                atomic_json(self.journal, state)
                return self._send_report(state)
            response.raise_for_status()
        else:
            if not self._heartbeat(state, 0.9):
                return False
            for preview in state["previews"]:
                path = self._safe_path(preview["path"])
                form = self._owner(state)
                if preview["digest"]:
                    form["artifact_sha256"] = preview["digest"]
                if not self._heartbeat(state, 0.9):
                    return False
                with path.open("rb") as handle:
                    response = self._request(
                        "POST",
                        endpoint + "/thumbnails",
                        data=form,
                        files={"file": (path.name, handle, "image/jpeg")},
                    )
                if response.status_code == 409:
                    return False
                if response.status_code in {413, 415}:
                    LOG.warning("跳过无效缩略图：%s", path.name)
                else:
                    response.raise_for_status()
            state["report_ready"] = True
            atomic_json(self.journal, state)
            return self._send_report(state)
        self.journal.unlink()
        LOG.info("%s 已回报 %s。", state["task"]["task_id"], action)
        return True

    def _media(self, state, command: list[str], *, cwd=None):
        # 媒体操作期间仍按租约周期检查，避免大文件转换阻塞心跳。
        try:
            with subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                start_new_session=os.name != "nt",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ) as process:
                deadline = time.monotonic() + state["task"]["timeout_seconds"]
                try:
                    while True:
                        try:
                            out, err = process.communicate(timeout=2)
                            return subprocess.CompletedProcess(
                                command, process.returncode, out, err
                            )
                        except subprocess.TimeoutExpired:
                            if time.monotonic() > deadline:
                                raise JobError("本地媒体操作超时。") from None
                            if not self._heartbeat(state, 0.9):
                                raise requests.ConnectionError("等待恢复任务租约") from None
                finally:
                    if process.poll() is None:
                        if os.name == "nt":
                            subprocess.run(
                                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                capture_output=True,
                                creationflags=subprocess.CREATE_NO_WINDOW,
                            )
                        else:
                            with contextlib.suppress(ProcessLookupError):
                                os.killpg(process.pid, signal.SIGKILL)
                        if process.poll() is None:
                            process.kill()
                        process.communicate()
        except FileNotFoundError as exc:
            raise JobError(f"未安装 {command[0]}。") from exc

    def _probe(self, state, path):
        return probe_json(self._media(state, probe_command(path)))

    def _qc(self, state, candidates):
        try:
            return check_candidates(self, state, candidates)
        except requests.RequestException:
            raise
        except (ValueError, KeyError, OSError) as exc:
            raise JobError(str(exc)) from exc

    def _assemble(self, state):
        root = str(Path(__file__).resolve().parents[2])
        if root not in sys.path:
            sys.path.insert(0, root)
        from tools.edit.edit.production import executor_plan

        started = time.monotonic()
        output = self.state_dir / "outputs" / state["stem"] / "episode.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            plan = executor_plan(
                state["task"]["payload"]["jobs"],
                resolve=self._safe_path,
                digest=lambda path: self._hash(path, state)[0],
            )
            plan_path = output.with_name("edit_plan.json")
            atomic_json(plan_path, plan)
            result = self._media(
                state,
                [
                    sys.executable,
                    "-X",
                    "utf8",
                    "-m",
                    "edit",
                    "assemble",
                    "--root",
                    str(self.root),
                    "--plan",
                    str(plan_path),
                    "--out",
                    str(output),
                ],
                cwd=Path(root) / "tools/edit",
            )
            if result.returncode or not output.is_file():
                raise JobError("本地剪辑失败。" + result.stderr.decode("utf-8", "replace")[-600:])
        except requests.RequestException:
            raise
        except (ValueError, OSError) as exc:
            raise JobError(str(exc)) from exc
        return {"ok": True, "outputs": [str(output)], "seconds": time.monotonic() - started}


def read_config(path: Path) -> BridgeConfig:
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    url = urlsplit(raw["mac_core_url"])
    if (
        url.scheme not in {"https", "http"}
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path not in {"", "/"}
    ):
        raise ValueError("mac_core_url 须为 Mac Core 根地址。")
    worker = raw["worker_id"]
    tags = tuple(raw.get("resource_tags", ["gpu-5070ti"]))
    lease = raw.get("lease_seconds", 90)
    if (
        not IDENTIFIER.fullmatch(worker)
        or not tags
        or not all(IDENTIFIER.fullmatch(tag) for tag in tags)
        or not 30 <= lease <= 3600
    ):
        raise ValueError("worker_id、resource_tags 或 lease_seconds 无效。")
    root = Path(raw["project_root"]).expanduser()
    if not root.is_dir():
        raise ValueError("project_root 须为现有的 Windows 项目目录。")
    return BridgeConfig(raw["mac_core_url"], worker, root, tags, lease)


def _pause_marker(config: BridgeConfig) -> Path:
    # 每个 worker_id 独立暂停，不修改 Mac Core 的任何生产配置。
    return config.root.resolve() / "_queue" / "executor_bridge" / (
        f"{config.worker_id}.pause-new.json"
    )


def manage_new_task_pause(config: BridgeConfig, action: str) -> dict:
    """Local operator control; never requires or prints a Core device token."""
    marker = _pause_marker(config)
    if marker.is_symlink() or marker.parent.is_symlink():
        raise ValueError("暂停标记目录或文件不能是符号链接。")
    if not marker.parent.resolve().is_relative_to(config.root.resolve()):
        raise ValueError("暂停标记不在现有 Windows 项目目录内。")
    if action == "pause":
        marker.parent.mkdir(parents=True, exist_ok=True)
        # 原子写入，重启后仍保留暂停；不会丢掉原有 Worker Journal。
        atomic_json(marker, {"version": 1, "mode": "pause-new-leases"})
    elif action == "resume":
        marker.unlink(missing_ok=True)
    elif action != "status":
        raise ValueError("无效暂停操作。")
    return {
        "worker_id": config.worker_id,
        "new_task_leases_paused": marker.exists(),
        "inflight_journal_preserved": True,
        "already_submitted_jobs_continue": True,
        "global_gpu_hold_unchanged": True,
        "scope": "THIS_WINDOWS_BRIDGE_ONLY",
    }


def main():
    parser = argparse.ArgumentParser(description="启动 Windows 执行桥")
    parser.add_argument(
        "config", type=Path, nargs="?", default=Path(__file__).with_name("executor_bridge.toml")
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--pause-new", action="store_true", help="暂停领取新任务")
    mode.add_argument("--resume-new", action="store_true", help="继续领取新任务")
    mode.add_argument("--pause-status", action="store_true", help="只读查看本机暂停状态")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        config = read_config(args.config)
        # 管理暂停只需本机项目配置，不需要长期设备 Token，且不会启动 Worker。
        action = (
            "pause" if args.pause_new else "resume" if args.resume_new
            else "status" if args.pause_status else None
        )
        if action:
            print(json.dumps(manage_new_task_pause(config, action), ensure_ascii=False))
            return
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(f"执行桥配置无效：{exc}")
    token = os.environ.get("PICOTOO_EXECUTOR_TOKEN")
    if not token:
        parser.error("请设置环境变量 PICOTOO_EXECUTOR_TOKEN。")
    with requests.Session() as session:
        session.trust_env = False
        session.headers["Authorization"] = f"Bearer {token}"
        bridge = Bridge(config, session)
        # 锁在进程退出时释放，避免同一台机器的两个进程改写同一个待报告任务。
        import msvcrt

        with (bridge.state_dir / f"{config.worker_id}.lock").open("a+b") as lock:
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                parser.error("相同 worker_id 的执行桥已在运行。")
            try:
                while True:
                    try:
                        bridge.step()
                    except (requests.RequestException, OSError) as exc:
                        LOG.warning("本地状态已保留，将重试：%s", exc)
                    time.sleep(POLL_SECONDS)
            except KeyboardInterrupt:
                LOG.info("执行桥已停止。")


if __name__ == "__main__":
    main()
