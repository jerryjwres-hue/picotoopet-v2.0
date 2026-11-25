#!/usr/bin/env python3
"""Mac-local Owner structured review (operator tool, not the Windows daily surface).

Runs ON the Mac mini, by the owner, in their own login session:

  provision  Generate one 256-bit owner-review secret, store it ONLY in the current user's
             login Keychain (service ``PicotooPetV2.OwnerReview.<credential_id>``) and write
             the fingerprint-only registry file (mode 0600). The secret is never printed,
             logged, passed on a command line or written to disk outside Keychain.
  review     Read that secret from Keychain and call the existing loopback-only Core API
             (GET proposal -> POST preview -> POST commit). Every field decision is the
             owner's; commit happens only after typing the exact confirmation phrase.

It never edits the database, never creates tasks or Goals, never touches GPU/HOLD, and
never sends the secret anywhere but ``http://127.0.0.1``/``http://[::1]`` on this Mac. Core
must be started with ``PICOTOO_OWNER_REVIEW_REGISTRY_FILE`` pointing at the registry and
restarted after provisioning (see README_OWNER_REVIEW_LOCAL_CN.md).

Standard library only; compatible with the macOS system Python 3.9.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlsplit

REQUIRED_FIELD_PATHS = (
    "subject_lock.subject_id",
    "subject_lock.species",
    "subject_lock.breed_or_type",
    "subject_lock.coat_or_appearance",
    "subject_lock.distinguishing_marks",
    "pose_lock.body_pose",
    "pose_lock.head_direction",
    "pose_lock.support_surface",
    "scene_lock.environment",
    "scene_lock.lighting",
    "scene_lock.temporary_accessories",
    "camera_lock.allowed_framings",
    "allowed_events",
)
DYNAMIC_PET_POLICY = "dynamic-pet-feeding-v1.0.0"
STATIC_PET_POLICY = "static-pet-story-v1.0.0"
CONFIRM_PHRASE = "确认提交"
KEYCHAIN_PREFIX = "PicotooPetV2.OwnerReview."
DEFAULT_REGISTRY = "~/Library/Application Support/PicotooPetV2/owner-review-registry.json"
DEFAULT_BASE_URL = "http://127.0.0.1:8765"
API_PREFIX = "/api/v1"  # every Core router is mounted under this prefix

_SUBJECT = re.compile(r"^pet:[a-z0-9][a-z0-9-]{1,63}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
_GOAL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")

Http = Callable[[str, str, Optional[Dict[str, Any]], Dict[str, str]], Dict[str, Any]]
Ask = Callable[[str], str]


def _fail(code: str) -> None:
    raise SystemExit(code)


# ── Keychain ─────────────────────────────────────────────────────────────────


class MacKeychain:
    """Current-user login Keychain; the secret is passed via stdin, never argv."""

    def store(self, service: str, secret: str) -> None:
        command = 'add-generic-password -U -a "{0}" -s "{1}" -w "{2}"\n'.format(
            getpass.getuser(), service, secret)
        result = subprocess.run(["/usr/bin/security", "-i"], input=command, text=True,
                                capture_output=True, timeout=15)
        if result.returncode != 0:
            _fail("OWNER_REVIEW_KEYCHAIN_WRITE_FAILED")

    def read(self, service: str) -> Optional[str]:
        if sys.platform != "darwin":
            return None
        try:
            result = subprocess.run(
                ["/usr/bin/security", "find-generic-password", "-a", getpass.getuser(),
                 "-s", service, "-w"],
                capture_output=True, text=True, timeout=15, check=True)
        except (OSError, subprocess.SubprocessError):
            return None
        value = result.stdout.strip()
        return value or None


# ── provision ────────────────────────────────────────────────────────────────


def _write_private_json(path: Path, document: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        _fail("OWNER_REVIEW_REGISTRY_SYMLINK")
    descriptor, temp = tempfile.mkstemp(prefix=".owner-review-", dir=str(path.parent))
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def provision(*, registry_path: Path, credential_id: str, actor_id: str,
              subject_keys: List[str], keychain: Any, out: Any) -> int:
    if not _ID.fullmatch(credential_id) or not _ID.fullmatch(actor_id):
        _fail("OWNER_REVIEW_ID_INVALID")
    if not subject_keys or len(set(subject_keys)) != len(subject_keys) or not all(
            _SUBJECT.fullmatch(key) for key in subject_keys):
        _fail("OWNER_REVIEW_SUBJECT_SCOPE_INVALID")

    credentials: List[Dict[str, Any]] = []
    revision = 0
    if registry_path.exists():
        if registry_path.is_symlink():
            _fail("OWNER_REVIEW_REGISTRY_SYMLINK")
        existing = json.loads(registry_path.read_text(encoding="utf-8"))
        if existing.get("schema_version") != "owner_review_registry.v1":
            _fail("OWNER_REVIEW_REGISTRY_INVALID")
        credentials = [item for item in existing.get("credentials", [])
                       if item.get("credential_id") != credential_id]
        revision = max([int(item.get("registry_revision", 0))
                        for item in existing.get("credentials", [])] or [0])

    secret = secrets.token_urlsafe(32)  # 43 URL-safe characters = 256 bits.
    keychain.store(KEYCHAIN_PREFIX + credential_id, secret)
    credentials.append({
        "credential_id": credential_id,
        "actor_id": actor_id,
        "token_sha256": hashlib.sha256(secret.encode("utf-8")).hexdigest(),
        "subject_keys": list(subject_keys),
        "permissions": ["owner_facts.review"],
        "registry_revision": revision + 1,
        "enabled": True,
    })
    del secret
    _write_private_json(registry_path, {"schema_version": "owner_review_registry.v1",
                                        "credentials": credentials})
    out.write("OWNER_REVIEW_PROVISIONED=PASS credential_id={0} subjects={1} revision={2}\n"
              .format(credential_id, ",".join(subject_keys), revision + 1))
    out.write("密钥只保存在本机钥匙串（{0}{1}），未显示、未写入文件。\n".format(KEYCHAIN_PREFIX, credential_id))
    out.write("下一步：让 Mac Core 以 PICOTOO_OWNER_REVIEW_REGISTRY_FILE={0} 重启（见 README）。\n"
              .format(registry_path))
    return 0


# ── review ───────────────────────────────────────────────────────────────────


def _loopback_base(base_url: str) -> str:
    parts = urlsplit(base_url)
    if (parts.scheme != "http" or parts.hostname not in ("127.0.0.1", "::1")
            or parts.username or parts.password or parts.path not in ("", "/")
            or parts.query or parts.fragment or parts.port is None):
        _fail("OWNER_REVIEW_LOOPBACK_URL_REQUIRED")
    host = "[::1]" if parts.hostname == "::1" else "127.0.0.1"
    return "http://{0}:{1}{2}".format(host, parts.port, API_PREFIX)


def urllib_http(method: str, url: str, body: Optional[Dict[str, Any]],
                headers: Dict[str, str]) -> Dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method, headers=dict(headers))
    if data is not None:
        request.add_header("Content-Type", "application/json")
    # Never follow proxies for a loopback owner call.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read().decode("utf-8"))
            code = detail.get("code") or detail.get("detail", {}).get("code") or ""
        except Exception:  # noqa: BLE001 - report the HTTP status only
            code = ""
        _fail("OWNER_REVIEW_HTTP_{0}{1}".format(error.code, (":" + str(code)) if code else ""))
    except urllib.error.URLError:
        _fail("OWNER_REVIEW_CORE_UNREACHABLE")
    return {}


def _show(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def review(*, goal_id: str, base_url: str, credential_id: str, keychain: Any,
           http: Http, ask: Ask, out: Any) -> int:
    if not _GOAL.fullmatch(goal_id) or not _ID.fullmatch(credential_id):
        _fail("OWNER_REVIEW_ID_INVALID")
    base = _loopback_base(base_url)
    secret = keychain.read(KEYCHAIN_PREFIX + credential_id)
    if not secret:
        _fail("OWNER_REVIEW_KEYCHAIN_SECRET_MISSING")
    headers = {"Authorization": "Bearer " + secret, "Accept": "application/json"}

    proposal = http("GET", "{0}/owner-structured-reviews/goals/{1}/proposal".format(base, goal_id),
                    None, headers)
    out.write("目标 {0} · 主体 {1} · 审核人 {2}\n".format(
        proposal["goal_id"], proposal["subject_key"], proposal["review_actor_id"]))
    out.write("来源证据 {0} 条；proposal_digest={1}\n\n".format(
        len(proposal.get("source_evidence", [])), proposal["proposal_digest"]))

    decisions: List[Dict[str, Any]] = []
    for path in REQUIRED_FIELD_PATHS:
        field = proposal["fields"].get(path) or {"status": "UNKNOWN", "value": None}
        status = field.get("status")
        out.write("[{0}] {1} = {2}\n".format(status, path, _show(field.get("value"))))
        if status == "EXPLICIT":
            decisions.append({"field_path": path, "decision": "CONFIRM"})
            continue
        choice = ask("  此字段需要你决定：x=更正（输入 JSON 值）/ u=保持未知：").strip().lower()
        if choice == "x":
            raw = ask("  更正值（JSON，例如 \"white mask\" 或 [\"a\",\"b\"]）：")
            try:
                value = json.loads(raw)
            except ValueError:
                _fail("OWNER_REVIEW_CORRECTION_NOT_JSON")
            decisions.append({"field_path": path, "decision": "CORRECT", "corrected_value": value})
        else:
            decisions.append({"field_path": path, "decision": "UNKNOWN"})

    preview_request: Dict[str, Any] = {
        "goal_id": proposal["goal_id"],
        "review_actor_id": proposal["review_actor_id"],
        "proposal_digest": proposal["proposal_digest"],
        "decisions": decisions,
    }
    motion = proposal.get("dynamic_motion_proposal")
    if motion is not None:
        out.write("\n动态镜头提案（motion_digest={0}）：\n{1}\n".format(
            motion["motion_digest"], _show(motion.get("motion"))))
        if ask("确认这段喂食动作提案？y/N：").strip().lower() == "y":
            preview_request["story_policy_opt_in"] = DYNAMIC_PET_POLICY
            preview_request["confirmed_motion_digest"] = motion["motion_digest"]
    elif ask("按静态宠物故事策略（固定姿势、静态机位）确认？y/N：").strip().lower() == "y":
        preview_request["story_policy_opt_in"] = STATIC_PET_POLICY

    preview = http("POST", base + "/owner-structured-reviews/preview", preview_request, headers)
    out.write("\n预览结果：{0} {1}\n".format(preview["outcome"], " ".join(preview.get("reason_codes", []))))
    if preview["outcome"] != "READY":
        out.write("未提交：预览不是 READY。\n")
        return 2

    phrase = ask("确认以 Owner 身份提交以上事实？请输入「{0}」：".format(CONFIRM_PHRASE)).strip()
    if phrase != CONFIRM_PHRASE:
        out.write("未提交：确认短语不匹配。\n")
        return 3
    commit_request = {
        "preview_request": preview_request,
        "source_revision_digest": preview["source_revision_digest"],
        "review_digest": preview["review_digest"],
        "preview_digest": preview["preview_digest"],
    }
    commit_headers = dict(headers)
    commit_headers["Idempotency-Key"] = "owner-review-local-" + preview["preview_digest"][:32]
    committed = http("POST", base + "/owner-structured-reviews/commit", commit_request, commit_headers)
    out.write("OWNER_REVIEW_COMMITTED=PASS commitment_id={0} facts_id={1}\n".format(
        committed.get("commitment_id"), committed.get("facts_id")))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="PicotooPet Mac 本机 Owner 审核（运维工具）")
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("provision", help="生成本机 Owner 审核凭据（仅钥匙串 + 指纹登记表）")
    p.add_argument("--credential-id", required=True)
    p.add_argument("--actor-id", required=True)
    p.add_argument("--subject", action="append", required=True, help="例如 pet:maotai")
    p.add_argument("--registry", default=DEFAULT_REGISTRY)
    r = commands.add_parser("review", help="审核一个 Goal 的主人事实并（确认后）提交")
    r.add_argument("--goal-id", required=True)
    r.add_argument("--credential-id", required=True)
    r.add_argument("--base-url", default=DEFAULT_BASE_URL)
    args = parser.parse_args(argv)
    if sys.platform != "darwin":
        _fail("OWNER_REVIEW_LOCAL_MACOS_REQUIRED")
    if args.command == "provision":
        return provision(registry_path=Path(args.registry).expanduser(),
                         credential_id=args.credential_id, actor_id=args.actor_id,
                         subject_keys=args.subject, keychain=MacKeychain(), out=sys.stdout)
    return review(goal_id=args.goal_id, base_url=args.base_url, credential_id=args.credential_id,
                  keychain=MacKeychain(), http=urllib_http, ask=input, out=sys.stdout)


if __name__ == "__main__":
    sys.exit(main())
