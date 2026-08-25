from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import io
import json
import zlib
import zipfile
from pathlib import Path, PurePosixPath


CORE_PREFIX = "payload/producer/extensions/director_console_native_v2/"                    # Frozen Director Core subtree.
DEFAULT_CHUNK_CHARS = 4800                                                                   # Small text chunks for GitHub contents API reliability.
INVENTORY_FILENAME = "N6D4_CORE_ENTRY_INVENTORY.json"                                      # Independent authority for the complete frozen Core file set.
EVIDENCE_FILENAME = "N6D4_CORE_ENTRY_EVIDENCE.json"                                        # Recovered compressed payload references for inventory entries.
PINNED_ENTRY_FIELDS = (                                                                      # Evidence may add evidence_file, but may not redefine ZIP metadata.
    "compression_method",
    "crc32",
    "compressed_size",
    "uncompressed_size",
    "local_header_offset",
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_core_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name.replace("\\", "/"))                                          # Normalize Windows separators before safety checks.
    drive_qualified = bool(path.parts and len(path.parts[0]) == 2 and path.parts[0][0].isalpha() and path.parts[0][1] == ":")
    if path.is_absolute() or ".." in path.parts or drive_qualified:
        raise ValueError(f"unsafe Core entry path: {name}")
    if not path.as_posix().startswith(CORE_PREFIX):
        raise ValueError(f"Core entry outside frozen Core prefix: {name}")
    return path


def _normalize_entry_metadata(entry: dict[str, object]) -> tuple[object, ...]:
    return (
        int(entry["compression_method"]),
        str(entry["crc32"]).lower(),
        int(entry["compressed_size"]),
        int(entry["uncompressed_size"]),
        int(entry["local_header_offset"]),
    )                                                                                       # Canonical tuple makes metadata comparison explicit and type-stable.


def _validate_unique_paths(entries: list[dict[str, object]], *, source_label: str) -> dict[str, dict[str, object]]:
    indexed: dict[str, dict[str, object]] = {}
    for entry in entries:
        name = str(entry["path"])
        _validate_core_path(name)                                                            # Reject traversal/out-of-prefix before set comparison hides the root cause.
        if name in indexed:
            if source_label == "evidence":
                raise ValueError(f"duplicate Core entry path: {name}")
            raise ValueError(f"duplicate authoritative Core inventory path: {name}")
        indexed[name] = entry
    return indexed


def _load_authoritative_inventory(evidence_dir: Path) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    inventory_path = evidence_dir / INVENTORY_FILENAME
    if not inventory_path.is_file():
        raise ValueError("authoritative N6D4 Core inventory is missing")
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))

    if inventory.get("source_checkpoint") != "N6D4":
        raise ValueError("authoritative Core inventory checkpoint is not N6D4")
    if inventory.get("inventory_status") != "complete":
        raise ValueError("authoritative Core inventory is not complete")
    if inventory.get("core_prefix") != CORE_PREFIX:
        raise ValueError("authoritative Core inventory prefix does not match frozen prefix")

    entries = list(inventory.get("entries", []))
    expected_count = int(inventory.get("core_entry_count", -1))
    if expected_count != len(entries) or expected_count < 1:
        raise ValueError(f"authoritative Core inventory count mismatch: expected={expected_count} actual={len(entries)}")
    indexed = _validate_unique_paths(entries, source_label="inventory")
    return inventory, indexed


def _read_entry_payload(evidence_dir: Path, entry: dict[str, object]) -> bytes:
    evidence_name = str(entry.get("evidence_file", ""))
    evidence_path = evidence_dir / evidence_name
    if not evidence_name or not evidence_path.is_file():
        raise ValueError(f"entry evidence is missing: {evidence_name or '<empty>'}")
    try:
        compressed = base64.b64decode(evidence_path.read_text(encoding="ascii").strip(), validate=True)
    except ValueError as exc:
        raise ValueError(f"entry evidence Base64 is invalid: {evidence_name}") from exc

    expected_compressed_size = int(entry["compressed_size"])
    if len(compressed) != expected_compressed_size:
        raise ValueError(
            f"compressed size mismatch for {entry['path']}: expected={expected_compressed_size} actual={len(compressed)}"
        )

    method = int(entry["compression_method"])
    if method == 0:
        data = compressed                                                                    # ZIP method 0 stores bytes without compression.
    elif method == 8:
        try:
            data = zlib.decompress(compressed, -15)                                          # ZIP method 8 uses raw DEFLATE framing.
        except zlib.error as exc:
            raise ValueError(f"DEFLATE decode failed for {entry['path']}") from exc
    else:
        raise ValueError(f"unsupported ZIP compression method {method} for {entry['path']}")

    expected_size = int(entry["uncompressed_size"])
    if len(data) != expected_size:
        raise ValueError(f"uncompressed size mismatch for {entry['path']}: expected={expected_size} actual={len(data)}")
    actual_crc = f"{binascii.crc32(data) & 0xffffffff:08x}"
    expected_crc = str(entry["crc32"]).lower()
    if actual_crc != expected_crc:
        raise ValueError(f"CRC32 mismatch for {entry['path']}: expected={expected_crc} actual={actual_crc}")
    return data


def _emit_bundle(
    *,
    output_dir: Path,
    files: list[tuple[str, bytes, str]],
    evidence: dict[str, object],
    inventory: dict[str, object],
    chunk_chars: int,
) -> dict[str, object]:
    if chunk_chars <= 0:
        raise ValueError("chunk_chars must be positive")

    buffer = io.BytesIO()
    manifest_files: list[dict[str, object]] = []
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data, source_crc in sorted(files, key=lambda item: item[0]):
            info = zipfile.ZipInfo(name, date_time=(2026, 8, 20, 0, 0, 0))                  # Fixed timestamp keeps the reconstructed Core bundle deterministic.
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)
            manifest_files.append(
                {
                    "path": name,
                    "sha256": _sha256(data),
                    "size_bytes": len(data),
                    "source_crc32": source_crc,
                }
            )

    bundle = buffer.getvalue()
    bundle_sha = _sha256(bundle)
    encoded = base64.b64encode(bundle).decode("ascii")
    chunks = [encoded[index : index + chunk_chars] for index in range(0, len(encoded), chunk_chars)]

    output_dir.mkdir(parents=True, exist_ok=True)
    for stale in output_dir.glob("core.part*.b64"):
        stale.unlink()
    for index, chunk in enumerate(chunks):
        (output_dir / f"core.part{index:02d}.b64").write_text(chunk + "\n", encoding="ascii")

    inventory_bytes = (json.dumps(inventory, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    manifest: dict[str, object] = {
        "schema_version": "1.3",
        "source_checkpoint": "N6D4",
        "source_mode": "n6d4_zip_entries_crc32",
        "source_script_sha256_pin": str(evidence["source_script_sha256_pin"]).lower(),
        "source_script_sha256_verified": False,
        "source_archive_sha256_pin": str(evidence["source_archive_sha256_pin"]).lower(),
        "source_archive_sha256_verified": False,
        "source_zip_entries_verified": True,
        "source_zip_entry_count": len(files),
        "authoritative_inventory_status": "complete",
        "authoritative_inventory_sha256": _sha256(inventory_bytes),
        "core_prefix": CORE_PREFIX,
        "core_bundle_sha256": bundle_sha,
        "core_file_count": len(files),
        "files": manifest_files,
    }
    (output_dir / "CORE_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "CORE_BUNDLE.sha256").write_text(f"{bundle_sha}  PVP_DirectorConsole_Core_N6D4.zip\n", encoding="ascii")
    (output_dir / "SOURCE_PROVENANCE.txt").write_text(
        "\n".join(
            [
                "SOURCE_MODE=n6d4_zip_entries_crc32",
                f"N6D4_SCRIPT_SHA256_PIN={str(evidence['source_script_sha256_pin']).lower()}",
                "N6D4_SCRIPT_SHA256_VERIFIED=NO",
                f"N6D4_ARCHIVE_SHA256_PIN={str(evidence['source_archive_sha256_pin']).lower()}",
                "N6D4_ARCHIVE_SHA256_VERIFIED=NO",
                "N6D4_CORE_INVENTORY_STATUS=complete",
                f"N6D4_CORE_INVENTORY_SHA256={manifest['authoritative_inventory_sha256']}",
                f"N6D4_ZIP_ENTRY_COUNT={len(files)}",
                "N6D4_ZIP_ENTRIES_VERIFIED=YES",
                "",
            ]
        ),
        encoding="ascii",
    )
    return manifest


def recover_core_entries(*, evidence_dir: Path, output_dir: Path, chunk_chars: int = DEFAULT_CHUNK_CHARS) -> dict[str, object]:
    inventory, inventory_by_path = _load_authoritative_inventory(evidence_dir)               # Completeness authority is independent from recovered evidence.

    manifest_path = evidence_dir / EVIDENCE_FILENAME
    if not manifest_path.is_file():
        raise ValueError("N6D4 Core entry evidence manifest is missing")
    evidence = json.loads(manifest_path.read_text(encoding="utf-8"))

    if evidence.get("source_checkpoint") != "N6D4":
        raise ValueError("entry evidence checkpoint is not N6D4")
    if evidence.get("source_mode") != "n6d4_zip_entries_crc32":
        raise ValueError("entry evidence source mode is invalid")
    if evidence.get("core_prefix") != CORE_PREFIX:
        raise ValueError("entry evidence Core prefix does not match frozen prefix")
    if evidence.get("source_archive_sha256_verified") is not False:
        raise ValueError("entry mode must not claim whole-archive SHA verification")
    if evidence.get("source_script_sha256_verified") is not False:
        raise ValueError("entry mode must not claim original script SHA verification")

    entries = list(evidence.get("entries", []))
    expected_count = int(evidence.get("complete_core_entry_count", -1))
    if expected_count != len(entries) or expected_count < 1:
        raise ValueError(f"Core entry evidence is incomplete: expected={expected_count} actual={len(entries)}")
    evidence_by_path = _validate_unique_paths(entries, source_label="evidence")

    if set(evidence_by_path) != set(inventory_by_path):
        missing = sorted(set(inventory_by_path) - set(evidence_by_path))
        extra = sorted(set(evidence_by_path) - set(inventory_by_path))
        raise ValueError(
            "evidence path set does not match authoritative Core inventory: "
            f"missing={missing} extra={extra}"
        )

    for name in sorted(inventory_by_path):
        if _normalize_entry_metadata(evidence_by_path[name]) != _normalize_entry_metadata(inventory_by_path[name]):
            raise ValueError(f"evidence metadata does not match authoritative Core inventory: {name}")

    missing_evidence = [
        str(entry.get("evidence_file", "")) or "<empty>"
        for entry in entries
        if not str(entry.get("evidence_file", ""))
        or not (evidence_dir / str(entry.get("evidence_file", ""))).is_file()
    ]                                                                                       # Report every known recovery gap before decoding any payload.
    if missing_evidence:
        raise ValueError(f"entry evidence is missing: {', '.join(missing_evidence)}")

    files: list[tuple[str, bytes, str]] = []
    for entry in entries:
        name = str(entry["path"])
        data = _read_entry_payload(evidence_dir, entry)
        files.append((name, data, str(entry["crc32"]).lower()))

    return _emit_bundle(
        output_dir=output_dir,
        files=files,
        evidence=evidence,
        inventory=inventory,
        chunk_chars=chunk_chars,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Recover N6D4 Director Core from individually verified ZIP-entry payload evidence.")
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    manifest = recover_core_entries(
        evidence_dir=Path(args.evidence_dir).resolve(),
        output_dir=Path(args.output_dir).resolve(),
    )
    print(json.dumps({"status": "pass", **manifest}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
