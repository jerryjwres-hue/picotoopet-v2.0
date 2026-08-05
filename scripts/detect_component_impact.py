#!/usr/bin/env python3
"""Classify changed repository paths without building unaffected native components."""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
from typing import Iterable

WORKER_PREFIXES = (
    "src/picotoopet_core/worker/",
    "src/picotoopet_core/diagnostics/",
    "scripts/mac/phase23-worker/",
    "deploy/macos/phase23-worker/",
    "tests/unit/worker/",
    "tests/integration/worker/",
)
WORKER_FILES = frozenset(
    {
        "src/picotoopet_core/queue/diagnostic_repository.py",
        "tests/contract/test_worker_runtime_source.py",
        "tests/contract/test_phase23_worker_delivery.py",
    }
)
CORE_PREFIXES = (
    "src/picotoopet_core/",
    "scripts/mac/phase23/",
    "deploy/macos/phase23/",
    "tests/integration/api/",
    "tests/integration/approvals/",
    "tests/integration/queue/",
    "tests/unit/approvals/",
    "tests/unit/api/",
    "tests/unit/queue/",
    "contracts/openapi/",
)
WINDOWS_PREFIXES = (
    "windows/desktop/",
    "tests/release/test_windows_",
    "tests/contract/test_windows_",
    "tests/security/",
)
WINDOWS_FILES = frozenset(
    {
        "contracts/release/project-goal-invariants.json",
        "scripts/stamp_windows_goal_integrity.py",
        "scripts/verify_project_goal_integrity.py",
        "tests/release/test_self_hosted_native_runner_fallback.py",
    }
)
SHARED_DEPENDENCY_FILES = frozenset({"pyproject.toml"})


def _normalise(path: str) -> str:
    """Return a safe repository-relative POSIX path for deterministic matching."""

    cleaned = path.strip().replace("\\", "/")
    if not cleaned:
        return ""
    pure = PurePosixPath(cleaned)
    if pure.is_absolute() or ".." in pure.parts:
        raise ValueError(f"invalid repository path: {path!r}")
    return pure.as_posix().lstrip("./")


def classify(paths: Iterable[str]) -> dict[str, bool]:
    """Return native build impact for Mac Core, Mac Worker, and Windows."""

    impact = {"core": False, "worker": False, "windows": False}
    for raw in paths:
        path = _normalise(raw)
        if not path or path.startswith("docs/"):
            continue

        worker_specific = path in WORKER_FILES or path.startswith(WORKER_PREFIXES)
        if worker_specific:
            impact["worker"] = True

        if path in SHARED_DEPENDENCY_FILES:
            impact["core"] = True
            impact["worker"] = True
            impact["windows"] = True
            continue

        if path.startswith(CORE_PREFIXES) and not worker_specific:
            impact["core"] = True
        if path in WINDOWS_FILES or path.startswith(WINDOWS_PREFIXES):
            impact["windows"] = True

        if path == ".github/workflows/macos-core-slice-b-ci.yml":
            impact["core"] = True
        elif path == ".github/workflows/macos-worker-slice-c-ci.yml":
            impact["worker"] = True
        elif path in {
            ".github/workflows/windows-control-center-ci.yml",
            ".github/workflows/windows-phase2-release.yml",
        }:
            impact["windows"] = True

    return impact


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*", help="Changed repository paths")
    parser.add_argument("--paths-file", type=Path)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--force", choices=("all", "core", "worker", "windows"))
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    paths = list(args.paths)
    if args.paths_file is not None:
        paths.extend(args.paths_file.read_text(encoding="utf-8").splitlines())
    impact = classify(paths)
    if args.force == "all":
        impact = {key: True for key in impact}
    elif args.force is not None:
        impact[args.force] = True

    if args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8", newline="\n") as output:
            for key, value in impact.items():
                output.write(f"{key}={'true' if value else 'false'}\n")
    print(json.dumps(impact, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
