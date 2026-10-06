from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


_TOOL_DIRECTORY = str(Path(__file__).resolve().parent)
if _TOOL_DIRECTORY not in sys.path:
    sys.path.insert(0, _TOOL_DIRECTORY)

from maotai_connector_geometry import validate_visible_connector_geometry  # noqa: E402
from maotai_manifest_contract import parse_manifest  # noqa: E402
from maotai_png_validation import (  # noqa: E402
    validate_png_asset,
    validate_structural_art_quality,
)


class CandidateValidationReport:
    """生成候选的局部 fail-closed 报告；允许逐 family 验收，不要求一次生成全部 44 个资产。"""

    __slots__ = ("ok", "errors", "checked_files")

    def __init__(
        self,
        errors: list[str],
        checked_files: list[str],
    ) -> None:
        self.ok            = not errors
        self.errors        = tuple(errors)
        self.checked_files = tuple(checked_files)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "checked_files": list(self.checked_files),
            "errors": list(self.errors),
        }


def validate_generated_candidates(
    candidate_root: Path | str,
    art_plan_path: Path | str,
) -> CandidateValidationReport:
    """只验收本轮已生成部件；技术 PNG、organic silhouette 与可见连接器合同必须同时通过。"""
    root = Path(candidate_root)
    if not root.is_dir():
        return CandidateValidationReport(
            [f"candidate directory missing: {root}"],
            [],
        )

    try:
        plan = _load_json_object(art_plan_path)
        jobs = _index_jobs(plan)
        manifest_path = _manifest_from_plan(plan, Path(art_plan_path))
        descriptors   = parse_manifest(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return CandidateValidationReport([f"candidate plan error: {error}"], [])

    actual = sorted(
        path.name
        for path in root.iterdir()
        if path.is_file() and path.suffix.lower() == ".png"
    )
    if not actual:
        return CandidateValidationReport(["candidate directory contains no PNG files"], [])

    errors: list[str]  = []
    checked: list[str] = []
    for file_name in actual:
        job = jobs.get(file_name)
        if job is None:
            errors.append(f"unexpected/unplanned candidate PNG: {file_name}")
            continue

        descriptor = descriptors.get(file_name)
        if descriptor is None:
            errors.append(f"candidate target missing from manifest: {file_name}")
            continue

        path = root / file_name
        checked.append(file_name)
        errors.extend(validate_png_asset(path, descriptor))

        quality = job.get("structural_quality")
        if quality is not None:
            if not isinstance(quality, dict):
                errors.append(f"art job structural_quality must be an object: {file_name}")
            else:
                errors.extend(validate_structural_art_quality(path, descriptor, quality))
                errors.extend(validate_visible_connector_geometry(path, descriptor, quality))

    return CandidateValidationReport(errors, checked)


def _load_json_object(path: Path | str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("art plan JSON must be an object")
    return payload


def _index_jobs(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    jobs = plan.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        raise ValueError("art plan must contain non-empty jobs")

    indexed: dict[str, dict[str, Any]] = {}
    for job in jobs:
        if not isinstance(job, dict):
            raise ValueError("each art job must be an object")
        target = job.get("target_file")
        if (
            not isinstance(target, str)
            or not target.endswith(".png")
            or Path(target).name != target
        ):
            raise ValueError(f"invalid art job target_file: {target!r}")
        if target in indexed:
            raise ValueError(f"duplicate art job target_file: {target}")
        indexed[target] = job
    return indexed


def _manifest_from_plan(plan: dict[str, Any], plan_path: Path) -> Path:
    source = plan.get("source_of_truth")
    if not isinstance(source, str) or not source:
        raise ValueError("art plan source_of_truth is missing")

    path = Path(source)
    if path.is_absolute():
        return path

    # Repo-relative first   : production plans store repository-relative manifest paths.
    repository_candidate = (_repository_root() / path).resolve()
    if repository_candidate.is_file():
        return repository_candidate

    # Fixture-relative next : contract tests may keep a temporary manifest beside the art plan.
    return (plan_path.resolve().parent / path).resolve()


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a partial Maotai v2 generated candidate family before any runtime promotion.",
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args   = _build_parser().parse_args(argv)
    report = validate_generated_candidates(args.candidates, args.plan)
    payload = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
