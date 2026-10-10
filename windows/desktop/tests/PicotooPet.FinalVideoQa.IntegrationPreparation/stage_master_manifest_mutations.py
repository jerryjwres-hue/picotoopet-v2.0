#!/usr/bin/env python3
"""Stage isolated C009A negative manifest cases FROM an existing real master specimen.

Does NOT synthesize a fake C009A artifact or call unknown C010A APIs. Copies only to
an initially empty disposable root; never edits the original master directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

MUTATIONS = {
    "production-job-mismatch": ("production_job_id", "suffix"),
    "production-package-mismatch": ("production_package_digest", "sha"),
    "production-plan-mismatch": ("production_plan_digest", "sha"),
    "creative-package-mismatch": ("creative_package_digest", "sha"),
    "source-c004-mismatch": ("c004_source_sha256", "sha"),
    "caption-plan-mismatch": ("caption_overlay_plan_digest", "sha"),
    "narration-plan-mismatch": ("narration_plan_digest", "sha"),
    "selected-visual-mismatch": ("selected_visual_sha256", "sha"),
    "master-input-digest-mismatch": ("master_input_digest", "sha"),
    "master-output-sha-mismatch": ("output_sha256", "sha"),
    "master-output-bytes-mismatch": ("output_bytes", "increment"),
    "master-audio-flag-mismatch": ("has_audio", "flip"),
    "narration-manifest-mismatch": ("narration_manifest_sha256", "sha_nullable"),
    "overlay-manifest-mismatch": ("c008b_manifest_sha256", "sha_nullable"),
}


def altered(value, policy):
    if policy == "sha" or policy == "sha_nullable":
        if value is None:
            return None
        return ("1" if value[0] == "0" else "0") + value[1:]
    if policy == "suffix":
        return value + "-incorrect"
    if policy == "increment":
        return value + 1
    if policy == "flip":
        return not value
    raise ValueError(policy)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, required=True,
                        help="Real C009A <job-key>/<master_input_digest> directory")
    parser.add_argument("--output", type=Path, required=True, help="Empty disposable root")
    args = parser.parse_args()
    source = args.artifact_dir.absolute()
    dest = args.output.absolute()
    if not source.is_dir() or source.is_symlink() or source.parent.is_symlink():
        parser.error("artifact-dir must be an ordinary C009A digest directory")
    if len(source.name) != 64 or any(ch not in "0123456789abcdef" for ch in source.name):
        parser.error("artifact-dir must be named by the exact lowercase MasterInputDigest")
    expected_names = {"master.mp4", "master-manifest.json"}
    if {p.name for p in source.iterdir()} != expected_names or any(p.is_symlink() for p in source.iterdir()):
        parser.error("real specimen must contain exactly master.mp4 and master-manifest.json as ordinary files")
    try:
        master = json.loads((source / "master-manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        parser.error(f"unable to read actual master manifest: {type(exc).__name__}")
    if not isinstance(master, dict) or master.get("master_input_digest") != source.name:
        parser.error("specimen digest dir does not match MasterManifest.master_input_digest")
    if master.get("schema_version") != "1.0" or any(key not in master for key, _ in MUTATIONS.values()):
        parser.error("expected C009A MasterManifest v1 fields are absent; do not guess schema")
    if dest.exists() and any(dest.iterdir()):
        parser.error("output must be an empty disposable directory")
    if source == dest or source in dest.parents or dest in source.parents:
        parser.error("output must be independent from original artifact")
    dest.mkdir(parents=True, exist_ok=True)
    index = []

    def stage(id_):
        target = dest / id_ / source.parent.name / source.name
        target.mkdir(parents=True)
        for filename in sorted(expected_names):
            shutil.copy2(source / filename, target / filename)
        return target

    for id_, (field, policy) in MUTATIONS.items():
        if master[field] is None and policy == "sha_nullable":
            index.append({"id": id_, "status": "NOT_APPLICABLE_TO_SPECIMEN", "field": field})
            continue
        target = stage(id_)
        modified = dict(master)
        modified[field] = altered(modified[field], policy)
        (target / "master-manifest.json").write_text(json.dumps(modified, indent=2) + "\n", encoding="utf-8")
        index.append({"id": id_, "status": "STAGED_BLOCKED_C010A_API", "field": field,
                      "expected_catalog_outcome": "MASTER_ARTIFACT_CONFLICT"})

    extra = stage("unexpected-directory-entry")
    (extra / "unapproved.txt").write_text("synthetic extra entry\n", encoding="utf-8")
    index.append({"id": "unexpected-directory-entry", "status": "STAGED_BLOCKED_C010A_API",
                  "expected_catalog_outcome": "MASTER_ARTIFACT_CONFLICT"})
    missing = stage("missing-master-manifest")
    (missing / "master-manifest.json").unlink()
    index.append({"id": "missing-master-manifest", "status": "STAGED_BLOCKED_C010A_API",
                  "expected_catalog_outcome": "MASTER_ARTIFACT_CONFLICT"})
    corrupt = stage("master-media-byte-tamper")
    with (corrupt / "master.mp4").open("r+b") as stream:
        if (corrupt / "master.mp4").stat().st_size == 0:
            parser.error("specimen master.mp4 is empty")
        old = stream.read(1)
        stream.seek(0)
        stream.write(bytes([old[0] ^ 1]))
    index.append({"id": "master-media-byte-tamper", "status": "STAGED_BLOCKED_C010A_API",
                  "expected_catalog_outcome": "MASTER_ARTIFACT_CONFLICT"})
    original_hash = hashlib.sha256()
    with (source / "master.mp4").open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            original_hash.update(chunk)
    (dest / "mutation-index.json").write_text(json.dumps({"schema": "c009a-negative-staging.v1",
        "fixture_origin": "copied-real-specimen", "original_master_input_digest": source.name,
        "original_master_sha256": original_hash.hexdigest(),
        "scenarios": index}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"STAGED_SCENARIOS={sum(x['status'].startswith('STAGED') for x in index)}")
    print(f"NOT_APPLICABLE={sum(x['status'].startswith('NOT_APPLICABLE') for x in index)}")
    print("C010A_INTEGRATION=BLOCKED until frozen callable receipt/QA API exists")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
