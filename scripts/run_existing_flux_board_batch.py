#!/usr/bin/env python3
"""Explicit Windows-only execution of a frozen FLUX creative-draft batch.

The SHA-pinned historical runner retains its original graph and private Comfy
startup. No Core approval, production lease, public endpoint or model download.
A durable local marker and existing GPU lock prevent uncertain retries.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys

# 01. The deployed tools are a closed scripts directory, not imports from
#     the current working directory or a user-supplied PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import prepare_existing_flux_board_shot as bridge
from collect_local_keyframe_outputs import collect_flux_batch

# 01. Exact historical production component paths; no caller-controlled
#     executable or remote endpoint. A different installation needs local verification.
COMFY = Path(r"D:\opc in D\AI\ComfyUI\ComfyUI")
PYTHON = Path(r"D:\opc in D\AI\ComfyUI\standalone-env\python.exe")


def _safe_path(path: Path) -> Path:
    # 02. Windows junctions are not necessarily reported as symlinks.
    path = path.absolute()
    for item in (*reversed(path.parents), path):
        try:
            facts = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(facts.st_mode) or (
            getattr(facts, "st_file_attributes", 0) & 0x400
        ):
            raise ValueError("FLUX_DRAFT_REPARSE_PATH")
    return path


def _hash(path: Path) -> str:
    return bridge._sha(bridge._read_regular(_safe_path(path)))


def _write_new(path: Path, raw: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


@contextmanager
def _windows_handle(path: Path, *, write: bool, create: bool, share: int):
    # 03. Same Windows mandatory share semantics as the C# GPU lock.
    #     Open handles are never inherited by the renderer subprocess.
    import msvcrt
    from ctypes import wintypes
    create_file = ctypes.WinDLL("kernel32", use_last_error=True).CreateFileW
    create_file.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                            ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create_file.restype = wintypes.HANDLE
    access = 0x80000000 | (0x40000000 if write else 0)
    handle = create_file(str(_safe_path(path)), access, share, None,
                         4 if create else 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error(), "FLUX_DRAFT_LOCK_UNAVAILABLE")
    flags = os.O_BINARY | (os.O_RDWR if write else os.O_RDONLY)
    try:
        descriptor = msvcrt.open_osfhandle(handle, flags)
    except Exception:
        close = ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle
        close.argtypes = [wintypes.HANDLE]
        close(handle)
        raise
    with os.fdopen(descriptor, "r+b" if write else "rb") as stream:
        yield stream


def _require_idle_journal(root: Path) -> None:
    # 04. The existing Worker owns canonical production journal records.
    #     Unknown, corrupt or unresolved entries all prevent draft execution.
    for path in root.glob("*.submission.json"):
        value = bridge._read_json(_safe_path(path))
        job, task = value.get("JobId"), value.get("TaskId")
        if (not isinstance(job, str) or not job or not isinstance(task, str) or not task
            or path.name != hashlib.sha256(f"{job}\n{task}".encode()).hexdigest() + ".submission.json"
            or value.get("Phase") != "Settled"
            or any(not isinstance(value.get(k), str) or not bridge.SHA_PATTERN.fullmatch(value[k])
                   for k in ("PlanDigest", "GraphDigest"))):
            raise ValueError("FLUX_DRAFT_PRODUCTION_PENDING")


def _require_ports_idle() -> None:
    # 05. Never start a second Comfy server beside an existing 8188/8190
    #     process; the original runner also enforces its VRAM threshold.
    for port in (8188, 8190):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                raise ValueError("FLUX_DRAFT_COMFY_ALREADY_RUNNING")


def stage_inputs(*, batch_dir: Path, runner: Path, stage: Path, comfy_input: Path) -> dict:
    """Copy only prepared and rehashed assets into a fresh runner namespace."""
    # 06. Never execute changed source or trust caller-provided graph JSON.
    raw = bridge._read_regular(_safe_path(runner), max_bytes=128_000)
    if bridge._sha(raw) != bridge.RUNNER_SHA256:
        raise ValueError("FLUX_DRAFT_RUNNER_CHANGED")
    batch = bridge._read_json(_safe_path(batch_dir / "batch_manifest.json"))
    jobs_raw = bridge._read_regular(_safe_path(batch_dir / "flux_board_jobs.json"), max_bytes=256_000)
    if bridge._sha(jobs_raw) != batch["runner_jobs_sha256"]:
        raise ValueError("FLUX_DRAFT_JOBS_CHANGED")
    jobs = json.loads(jobs_raw, object_pairs_hook=bridge._json_pairs)
    if jobs["out"] != batch["runner_output_directory"] or len(jobs["jobs"]) != len(batch["shots"]):
        raise ValueError("FLUX_DRAFT_JOB_SCOPE_MISMATCH")
    staged: dict[str, str] = {}
    names: dict[str, str] = {}
    for record, job in zip(batch["shots"], jobs["jobs"], strict=True):
        folder = batch_dir / record["relative_directory"]
        proof_raw = bridge._read_regular(_safe_path(folder / "flux_board_handoff_manifest.json"))
        if bridge._sha(proof_raw) != record["handoff_manifest_sha256"]:
            raise ValueError("FLUX_DRAFT_HANDOFF_CHANGED")
        proof = json.loads(proof_raw, object_pairs_hook=bridge._json_pairs)
        if job["refs"] != [entry["relative_path"] for entry in proof["references"]]:
            raise ValueError("FLUX_DRAFT_REFERENCE_SCOPE_MISMATCH")
        for entry in proof["references"]:
            relative = entry["relative_path"]
            original = _safe_path(bridge._resolve_ref(runner.parent, relative))
            data = bridge._read_regular(original)
            digest = bridge._sha(data)
            if digest != entry["sha256"] or len(data) != entry["bytes"]:
                raise ValueError("FLUX_DRAFT_REFERENCE_CHANGED")
            basename = ("PTV2_" + original.name).casefold()
            if basename in names and names[basename] != digest:
                raise ValueError("FLUX_DRAFT_REFERENCE_BASENAME_COLLISION")
            names[basename] = digest
            # Historical runner copies by basename. Never overwrite different
            # existing Comfy input bytes; identical content is permitted.
            destination = _safe_path(comfy_input / ("PTV2_" + original.name))
            if destination.exists() and _hash(destination) != digest:
                raise ValueError("FLUX_DRAFT_COMFY_INPUT_COLLISION")
            if relative in staged:
                if staged[relative] != digest:
                    raise ValueError("FLUX_DRAFT_REFERENCE_CHANGED")
                continue
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            _write_new(target, data)
            staged[relative] = digest
    _write_new(stage / "run_flux_board.py", raw)
    _write_new(stage / "flux_board_jobs.json", jobs_raw)
    return batch


def execute(args: argparse.Namespace) -> Path:
    if sys.platform != "win32":
        raise ValueError("FLUX_DRAFT_WINDOWS_REQUIRED")
    # 07. Explicit standalone creative draft, only while the existing
    #     acceptance gate is HOLD. Never modify the gate or a Core job.
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise ValueError("FLUX_DRAFT_LOCALAPPDATA_REQUIRED")
    journal = _safe_path(Path(local) / "PicotooPetV2" / "MediaWorker" / "v1")
    if not journal.is_dir():
        raise ValueError("FLUX_DRAFT_EXISTING_JOURNAL_REQUIRED")
    marker = journal / "flux-draft-in-progress.json"
    gate = journal / "three-shot-acceptance.json"
    stage = _safe_path(args.run_dir)
    if stage.exists() or not stage.parent.is_dir():
        raise ValueError("FLUX_DRAFT_NEW_RUN_DIRECTORY_REQUIRED")
    # Validate the LoRA actually visible to the historical Comfy instance,
    # not an unrelated same-named copy supplied by the operator.
    lora = _safe_path(COMFY / "models" / "loras" / "maotai_lora_v2.safetensors")
    if lora != _safe_path(args.lora) or _hash(lora) != bridge.LORA_V2_SHA256:
        raise ValueError("FLUX_DRAFT_ACTIVE_LORA_MISMATCH")
    if not _safe_path(PYTHON).is_file() or not _safe_path(COMFY / "main.py").is_file():
        raise ValueError("FLUX_DRAFT_LEGACY_INSTALLATION_MISSING")
    comfy_input = _safe_path(COMFY / "input")
    if not comfy_input.is_dir():
        raise ValueError("FLUX_DRAFT_COMFY_INPUT_MISSING")

    with _windows_handle(journal / "gpu.lock", write=True, create=True, share=0):
        with _windows_handle(gate, write=False, create=False, share=1) as hold:
            if json.loads(hold.read(1025), object_pairs_hook=bridge._json_pairs) != {
                "schema_version": "1.0", "mode": "hold"
            } or not _safe_path(Path(str(gate) + ".armed")).is_file():
                raise ValueError("FLUX_DRAFT_HOLD_REQUIRED")
            if marker.exists():
                raise ValueError("FLUX_DRAFT_RECONCILIATION_REQUIRED")
            with _windows_handle(journal / "journal.lock", write=True, create=True, share=0):
                _require_idle_journal(journal)
            _require_ports_idle()
            stage.mkdir()
            batch_dir = stage / "prepared"
            # 08. Regenerate from the exact frozen ZIP and existing builder.
            #     This is not a generic arbitrary-graph execution endpoint.
            bridge.prepare_package_batch(
                package_file=_safe_path(args.package), package_sha=args.package_sha256,
                bindings_file=_safe_path(args.reference_map), runner_file=_safe_path(args.runner),
                lora_file=lora, output_dir=batch_dir, variant=args.variant, selected_shot=args.shot,
            )
            batch = stage_inputs(batch_dir=batch_dir, runner=args.runner, stage=stage,
                                 comfy_input=comfy_input)
            # 09. Durable marker before starting any GPU process. On timeout,
            #     crash, incomplete output or uncertain cleanup it remains HOLD.
            _write_new(marker, json.dumps({
                "schema": "picotoo.flux-draft-in-progress.v1",
                "batch_sha256": _hash(batch_dir / "batch_manifest.json"),
                "creative_package_sha256": args.package_sha256,
                "variant": args.variant,
            }, sort_keys=True).encode())
            # Keep the original verified runner and its fixed private Comfy
            # startup. It receives only the newly staged, hash-bound jobs file.
            # No shell, no API keys, no model update.
            with (stage / "execution.log").open("xb") as log:
                result = subprocess.run([str(PYTHON), "-B", str(stage / "run_flux_board.py"),
                                         "flux_board_jobs.json"],
                                        cwd=stage, stdin=subprocess.DEVNULL, stdout=log,
                                        stderr=subprocess.STDOUT, check=False, timeout=2400)
            if result.returncode != 0:
                raise ValueError("FLUX_DRAFT_RUNNER_FAILED")
            _require_ports_idle()
            # 10. The legacy runner can exit zero after a failed individual
            #     shot; exact embedded-graph collection must pass ALL shots.
            out = stage / batch["runner_output_directory"]
            candidates = collect_flux_batch(batch_dir, None, _safe_path(out))
            # Keep a common root across multiple variants: select run_dir.parent
            # once in the existing desktop candidate preview.
            prefix = (Path(stage.name) / out.name).as_posix()
            for shot in candidates["shots"]:
                for candidate in shot["candidates"]:
                    candidate["output_relative_path"] = prefix + "/" + candidate["output_relative_path"]
            report = stage / "keyframe-candidates.json"
            _write_new(report, json.dumps(candidates, ensure_ascii=False, sort_keys=True).encode())
            marker.unlink()
            return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--package-sha256", required=True)
    parser.add_argument("--reference-map", type=Path, required=True)
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--lora", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--variant", type=int, default=0)
    parser.add_argument("--shot")
    parser.add_argument("--execute", action="store_true", help="explicit local GPU draft consent")
    args = parser.parse_args()
    if not args.execute:
        parser.error("--execute is required; use prepare_existing_flux_board_shot.py for CPU-only preparation")
    report = execute(args)
    print("FLUX_DRAFT_CANDIDATES_READY=" + str(report))
    print("PRODUCTION_AUTHORIZED=FALSE; OWNER_APPROVED=FALSE; VISUAL_REVIEW=REQUIRED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
