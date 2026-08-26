from __future__ import annotations

import argparse
import json
from pathlib import Path


CORE_PREFIX = "payload/producer/extensions/director_console_native_v2/"                    # Frozen Director Core subtree.
LOCAL_FILE_HEADER_FIXED_BYTES = 30                                                           # ZIP local-file header before filename/extra fields.


def _minimum_local_entry_end(entry: dict[str, object]) -> int:
    name = str(entry["path"])
    return (
        int(entry["local_header_offset"])
        + LOCAL_FILE_HEADER_FIXED_BYTES
        + len(name.encode("utf-8"))
        + int(entry["compressed_size"])
    )                                                                                       # Extra-field length is unknown here; this is a safe lower bound only.


def audit_inventory(inventory_path: Path) -> dict[str, object]:
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    if inventory.get("source_checkpoint") != "N6D4":
        raise ValueError("Core inventory checkpoint is not N6D4")
    if inventory.get("core_prefix") != CORE_PREFIX:
        raise ValueError("Core inventory prefix does not match frozen prefix")

    status = str(inventory.get("inventory_status", ""))
    if status not in {"partial", "complete"}:
        raise ValueError(f"unsupported Core inventory status: {status or '<empty>'}")

    entries = list(inventory.get("entries", []))
    declared_verified = int(inventory.get("verified_entry_count", len(entries)))
    if declared_verified != len(entries):
        raise ValueError(
            f"verified Core inventory count mismatch: declared={declared_verified} actual={len(entries)}"
        )
    if not entries:
        raise ValueError("Core inventory has no verified entries")

    seen_paths: set[str] = set()
    seen_offsets: set[int] = set()
    ordered: list[dict[str, object]] = []
    for entry in entries:
        name = str(entry["path"])
        if not name.startswith(CORE_PREFIX):
            raise ValueError(f"Core inventory entry is outside frozen prefix: {name}")
        if name in seen_paths:
            raise ValueError(f"duplicate Core inventory path: {name}")
        offset = int(entry["local_header_offset"])
        if offset < 0:
            raise ValueError(f"negative Core ZIP local header offset: {name}")
        if offset in seen_offsets:
            raise ValueError(f"duplicate Core ZIP local header offset: {offset}")
        if int(entry["compressed_size"]) < 0 or int(entry["uncompressed_size"]) < 0:
            raise ValueError(f"negative Core ZIP entry size: {name}")
        seen_paths.add(name)
        seen_offsets.add(offset)
        ordered.append(entry)

    ordered.sort(key=lambda item: int(item["local_header_offset"]))
    gaps: list[dict[str, object]] = []
    for current, following in zip(ordered, ordered[1:]):
        current_end = _minimum_local_entry_end(current)
        following_start = int(following["local_header_offset"])
        if following_start < current_end:
            raise ValueError(
                "overlapping Core ZIP entry spans: "
                f"{current['path']} min_end={current_end} next={following['path']} offset={following_start}"
            )
        if following_start > current_end:
            gaps.append(
                {
                    "after_path": str(current["path"]),
                    "before_path": str(following["path"]),
                    "gap_start": current_end,
                    "gap_end": following_start,
                    "gap_bytes": following_start - current_end,
                }
            )

    if status == "complete":
        expected_count = int(inventory.get("core_entry_count", -1))
        if expected_count != len(entries):
            raise ValueError(
                f"complete Core inventory count mismatch: declared={expected_count} actual={len(entries)}"
            )
        if gaps:
            raise ValueError(f"complete Core inventory still has unexplained gaps: {len(gaps)}")

    return {
        "source_checkpoint": "N6D4",
        "status": status,
        "verified_entry_count": len(entries),
        "unexplained_gap_count": len(gaps),
        "unexplained_gap_bytes": sum(int(gap["gap_bytes"]) for gap in gaps),
        "gaps": gaps,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit N6D4 Director Core inventory ZIP-local offset continuity.")
    parser.add_argument("--inventory", required=True)
    args = parser.parse_args()

    result = audit_inventory(Path(args.inventory).resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
