from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path, PurePosixPath


N6D4_SCRIPT_SHA256 = "616b0732dbb3fa4160f1e980a776c86d184c3f58b31bcbc8879734f6abcf0b99"  # Pinned authoritative N6D4 script hash.
N6D4_ARCHIVE_SHA256 = "ea291ce62444c7c327b8e1f19a8db22b83e0b3c75e3684d0af32953ebc713ca1"  # Pinned authoritative embedded ZIP hash.
CORE_PREFIX = "payload/producer/extensions/director_console_native_v2/"                    # Frozen Director Core subtree inside N6D4.
DEFAULT_CHUNK_CHARS = 4800                                                                   # Small text chunks for GitHub contents API reliability.


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _extract_archive_bytes(script_text: str) -> bytes:
    match = re.search(r"\$ArchiveBase64\s*=\s*@'\s*(.*?)\s*'@", script_text, flags=re.DOTALL)
    if match is None:
        raise ValueError("ArchiveBase64 here-string is missing")
    compact = "".join(match.group(1).split())
    try:
        return base64.b64decode(compact, validate=True)
    except ValueError as exc:
        raise ValueError("ArchiveBase64 is invalid") from exc


def _validate_member_path(name: str) -> None:
    path = PurePosixPath(name.replace("\\", "/"))                                      # Normalize Windows ZIP separators before traversal checks.
    drive_qualified = bool(path.parts and len(path.parts[0]) == 2 and path.parts[0][0].isalpha() and path.parts[0][1] == ":")
    if path.is_absolute() or ".." in path.parts or drive_qualified:
        raise ValueError(f"unsafe ZIP member path: {name}")


def _build_core_bundle(source_archive: bytes) -> tuple[bytes, list[dict[str, object]]]:
    files: list[tuple[str, bytes, int]] = []
    with zipfile.ZipFile(io.BytesIO(source_archive), "r") as source:
        bad_member = source.testzip()
        if bad_member is not None:
            raise ValueError(f"source ZIP CRC failure: {bad_member}")
        for info in source.infolist():
            _validate_member_path(info.filename)
            if info.is_dir() or not info.filename.startswith(CORE_PREFIX):
                continue
            files.append((info.filename, source.read(info), info.CRC))

    if not files:
        raise ValueError("Director Core subtree is missing")

    files.sort(key=lambda item: item[0])
    bundle_buffer = io.BytesIO()
    manifest_files: list[dict[str, object]] = []
    with zipfile.ZipFile(bundle_buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for name, data, source_crc in files:
            info = zipfile.ZipInfo(name, date_time=(2026, 8, 20, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            bundle.writestr(info, data)
            manifest_files.append(
                {
                    "path": name,
                    "sha256": _sha256_bytes(data),
                    "size_bytes": len(data),
                    "source_crc32": f"{source_crc:08x}",
                }
            )
    return bundle_buffer.getvalue(), manifest_files


def _emit_core_bundle(
    *,
    source_archive: bytes,
    output_dir: Path,
    source_mode: str,
    source_script_sha256_pin: str,
    source_script_sha256_verified: bool,
    source_script_sha256: str | None,
    expected_archive_sha256: str,
    chunk_chars: int,
) -> dict[str, object]:
    actual_archive_sha = _sha256_bytes(source_archive)                                                # Archive identity is always verified before ZIP parsing.
    if actual_archive_sha != expected_archive_sha256.lower():
        raise ValueError(f"archive SHA-256 mismatch: expected={expected_archive_sha256.lower()} actual={actual_archive_sha}")

    bundle_bytes, manifest_files = _build_core_bundle(source_archive)
    bundle_sha = _sha256_bytes(bundle_bytes)
    encoded = base64.b64encode(bundle_bytes).decode("ascii")
    if chunk_chars <= 0:
        raise ValueError("chunk_chars must be positive")

    output_dir.mkdir(parents=True, exist_ok=True)
    for stale in output_dir.glob("core.part*.b64"):
        stale.unlink()
    chunks = [encoded[index : index + chunk_chars] for index in range(0, len(encoded), chunk_chars)]
    for index, chunk in enumerate(chunks):
        (output_dir / f"core.part{index:02d}.b64").write_text(chunk + "\n", encoding="ascii")

    manifest: dict[str, object] = {
        "schema_version": "1.1",
        "source_checkpoint": "N6D4",
        "source_mode": source_mode,
        "source_script_sha256_pin": source_script_sha256_pin.lower(),
        "source_script_sha256_verified": source_script_sha256_verified,
        "source_archive_sha256": actual_archive_sha,
        "source_archive_sha256_verified": True,
        "core_prefix": CORE_PREFIX,
        "core_bundle_sha256": bundle_sha,
        "core_file_count": len(manifest_files),
        "files": manifest_files,
    }
    if source_script_sha256 is not None:
        manifest["source_script_sha256"] = source_script_sha256.lower()                               # Preserve legacy field when raw script bytes were actually verified.

    (output_dir / "CORE_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "CORE_BUNDLE.sha256").write_text(f"{bundle_sha}  PVP_DirectorConsole_Core_N6D4.zip\n", encoding="ascii")
    (output_dir / "SOURCE_PROVENANCE.txt").write_text(
        "\n".join(
            [
                f"SOURCE_MODE={source_mode}",
                f"N6D4_SCRIPT_SHA256_PIN={source_script_sha256_pin.lower()}",
                f"N6D4_SCRIPT_SHA256_VERIFIED={'YES' if source_script_sha256_verified else 'NO'}",
                f"N6D4_ARCHIVE_SHA256={actual_archive_sha}",
                "N6D4_ARCHIVE_SHA256_VERIFIED=YES",
                "",
            ]
        ),
        encoding="ascii",
    )
    return manifest


def recover_core_archive(
    *,
    archive_bytes: bytes,
    output_dir: Path,
    expected_archive_sha256: str,
    source_script_sha256_pin: str = N6D4_SCRIPT_SHA256,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
) -> dict[str, object]:
    return _emit_core_bundle(
        source_archive=archive_bytes,
        output_dir=output_dir,
        source_mode="embedded_archive_sha256",
        source_script_sha256_pin=source_script_sha256_pin,
        source_script_sha256_verified=False,                                                           # Archive mode proves payload identity, not original PowerShell byte layout.
        source_script_sha256=None,
        expected_archive_sha256=expected_archive_sha256,
        chunk_chars=chunk_chars,
    )


def recover_core_bundle(
    *,
    output_dir: Path,
    script_bytes: bytes | None = None,
    script_text: str | None = None,
    expected_script_sha256: str,
    expected_archive_sha256: str,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
) -> dict[str, object]:
    if (script_bytes is None) == (script_text is None):
        raise ValueError("provide exactly one of script_bytes or script_text")
    raw_script = script_bytes if script_bytes is not None else script_text.encode("utf-8")              # Hash exact source bytes whenever available.
    actual_script_sha = _sha256_bytes(raw_script)                                                        # Sidecar comparison happens before decoding.

    if actual_script_sha != expected_script_sha256.lower():
        raise ValueError(f"script SHA-256 mismatch: expected={expected_script_sha256.lower()} actual={actual_script_sha}")

    if script_text is None:
        try:
            script_text = raw_script.decode("utf-8-sig")                                               # Decode only after exact raw-byte SHA passes.
        except UnicodeDecodeError as exc:
            raise ValueError("N6D4 script is not valid UTF-8") from exc

    source_archive = _extract_archive_bytes(script_text)
    return _emit_core_bundle(
        source_archive=source_archive,
        output_dir=output_dir,
        source_mode="all_in_one_script_sha256",
        source_script_sha256_pin=expected_script_sha256,
        source_script_sha256_verified=True,
        source_script_sha256=actual_script_sha,
        expected_archive_sha256=expected_archive_sha256,
        chunk_chars=chunk_chars,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Recover the frozen N6D4 Director Core subtree into a deterministic GitHub bundle.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--all-in-one", help="Path to PVP_DirectorConsole_Native_V2_0_N6D4_ALL_IN_ONE_2026-08-20.ps1")
    source.add_argument("--archive-zip", help="Path to the byte-exact embedded N6D4 ZIP; its pinned SHA-256 is mandatory")
    parser.add_argument("--output-dir", required=True, help="Directory that will receive CORE_BUNDLE metadata and core.part*.b64")
    args = parser.parse_args()

    if args.all_in_one:
        script_bytes = Path(args.all_in_one).read_bytes()                                                # Preserve BOM and CRLF for authoritative script SHA verification.
        manifest = recover_core_bundle(
            script_bytes=script_bytes,
            output_dir=Path(args.output_dir),
            expected_script_sha256=N6D4_SCRIPT_SHA256,
            expected_archive_sha256=N6D4_ARCHIVE_SHA256,
        )
    else:
        archive_bytes = Path(args.archive_zip).read_bytes()                                              # Archive mode accepts only bytes matching the authoritative embedded ZIP pin.
        manifest = recover_core_archive(
            archive_bytes=archive_bytes,
            output_dir=Path(args.output_dir),
            expected_archive_sha256=N6D4_ARCHIVE_SHA256,
            source_script_sha256_pin=N6D4_SCRIPT_SHA256,
        )

    print(json.dumps({"status": "pass", **manifest}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
