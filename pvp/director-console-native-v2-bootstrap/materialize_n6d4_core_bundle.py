from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import shutil
import zipfile
from pathlib import Path, PurePosixPath


CORE_PREFIX = "payload/producer/extensions/director_console_native_v2/"  # Frozen Director Core extraction boundary.


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_member(name: str) -> PurePosixPath:
    path = PurePosixPath(name.replace("\\", "/"))                                  # Normalize alternate ZIP separators before safety checks.
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe Core bundle path: {name}")
    normalized = path.as_posix()
    if not normalized.startswith(CORE_PREFIX):
        raise ValueError(f"Core bundle member outside frozen Core prefix: {name}")
    return path


def _read_bundle(bootstrap_dir: Path) -> bytes:
    parts = sorted(bootstrap_dir.glob("core.part*.b64"))
    if not parts:
        raise ValueError("Core bundle parts are missing")
    encoded = "".join(path.read_text(encoding="ascii").strip() for path in parts)     # Preserve deterministic lexical part order.
    try:
        return base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise ValueError("Core bundle Base64 is invalid") from exc


def materialize_core_bundle(*, bootstrap_dir: Path, target_root: Path) -> dict[str, object]:
    sha_path = bootstrap_dir / "CORE_BUNDLE.sha256"
    manifest_path = bootstrap_dir / "CORE_MANIFEST.json"
    provenance_path = bootstrap_dir / "SOURCE_PROVENANCE.txt"
    for required in (sha_path, manifest_path, provenance_path):
        if not required.is_file():
            raise ValueError(f"required Core metadata is missing: {required.name}")

    bundle = _read_bundle(bootstrap_dir)
    expected_bundle_sha = sha_path.read_text(encoding="ascii").split()[0].lower()
    actual_bundle_sha = _sha256(bundle)
    if actual_bundle_sha != expected_bundle_sha:
        raise ValueError(f"Core bundle SHA-256 mismatch: expected={expected_bundle_sha} actual={actual_bundle_sha}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("source_checkpoint") != "N6D4":
        raise ValueError("Core manifest source checkpoint is not N6D4")
    if manifest.get("core_prefix") != CORE_PREFIX:
        raise ValueError("Core manifest prefix does not match frozen Core prefix")
    if manifest.get("core_bundle_sha256", "").lower() != actual_bundle_sha:
        raise ValueError("Core manifest bundle SHA does not match reconstructed bundle")

    manifest_entries = {entry["path"]: entry for entry in manifest.get("files", [])}
    if manifest.get("core_file_count") != len(manifest_entries):
        raise ValueError("Core manifest file count is inconsistent")

    verified_files: list[tuple[PurePosixPath, bytes]] = []
    with zipfile.ZipFile(io.BytesIO(bundle), "r") as archive:
        bad_member = archive.testzip()
        if bad_member is not None:
            raise ValueError(f"Core bundle CRC failure: {bad_member}")

        archive_names = [info.filename for info in archive.infolist() if not info.is_dir()]
        if set(archive_names) != set(manifest_entries):
            raise ValueError("Core bundle file set does not match CORE_MANIFEST.json")

        for name in archive_names:
            safe_path = _validate_member(name)
            data = archive.read(name)
            entry = manifest_entries[name]
            actual_file_sha = _sha256(data)
            if actual_file_sha != str(entry["sha256"]).lower():
                raise ValueError(f"Core file SHA-256 mismatch: {name}")
            if len(data) != int(entry["size_bytes"]):
                raise ValueError(f"Core file size mismatch: {name}")
            verified_files.append((safe_path, data))

    core_root = target_root / PurePosixPath(CORE_PREFIX)                               # Remove stale Core only after every byte is verified.
    if core_root.exists():
        shutil.rmtree(core_root)
    for relative_path, data in verified_files:
        output = target_root.joinpath(*relative_path.parts)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)

    return {
        "status": "pass",
        "bundle_sha256": actual_bundle_sha,
        "file_count": len(verified_files),
        "core_root": str(core_root),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize the pinned N6D4 Director Core bundle into a reconstructed source tree.")
    parser.add_argument("--bootstrap-dir", required=True)
    parser.add_argument("--target-root", required=True)
    args = parser.parse_args()

    result = materialize_core_bundle(
        bootstrap_dir=Path(args.bootstrap_dir).resolve(),
        target_root=Path(args.target_root).resolve(),
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
