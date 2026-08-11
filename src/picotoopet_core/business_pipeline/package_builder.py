"""Pure Return Package v1 builder from trusted Mac Core records."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .models import BusinessPipelineRunRecord


def _require_identity(actual: object, expected: object, code: str) -> None:
    if actual != expected:
        raise ValueError(code)


def _as_dict(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("PIPELINE_PROVENANCE_INVALID")
    return value


def build_return_package(
    *,
    return_package_id: str,
    run: BusinessPipelineRunRecord,
    work_package: object,
    result_package: object,
    creative_package: object,
    production_package: object,
) -> dict[str, object]:
    """Freeze end-to-end identities and evidence without copying source datasets."""

    _require_identity(getattr(work_package, "work_package_id"), run.work_package_id, "PIPELINE_WORK_ID_MISMATCH")
    _require_identity(getattr(result_package, "work_package_id"), run.work_package_id, "PIPELINE_RESULT_WORK_MISMATCH")
    _require_identity(getattr(result_package, "result_package_id"), run.result_package_id, "PIPELINE_RESULT_ID_MISMATCH")
    _require_identity(
        getattr(creative_package, "creative_package_id"),
        run.creative_package_id,
        "PIPELINE_CREATIVE_ID_MISMATCH",
    )
    _require_identity(
        getattr(production_package, "production_package_id"),
        run.production_package_id,
        "PIPELINE_PRODUCTION_ID_MISMATCH",
    )
    _require_identity(
        getattr(production_package, "creative_package_id"),
        run.creative_package_id,
        "PIPELINE_PRODUCTION_CREATIVE_MISMATCH",
    )

    production_manifest = _as_dict(getattr(production_package, "manifest"))
    if production_manifest.get("quality_outcome") != "PASS":
        raise ValueError("PIPELINE_PRODUCTION_PACKAGE_NOT_PASS")
    outputs = production_manifest.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise ValueError("PIPELINE_PRODUCTION_OUTPUTS_MISSING")
    for output in outputs:
        if not isinstance(output, dict):
            raise ValueError("PIPELINE_PRODUCTION_OUTPUT_INVALID")
        digest = output.get("output_sha256")
        size = output.get("output_bytes")
        if not isinstance(digest, str) or len(digest) != 64 or not isinstance(size, int) or size < 0:
            raise ValueError("PIPELINE_PRODUCTION_OUTPUT_EVIDENCE_INVALID")

    warnings = list(getattr(result_package, "warnings", []) or [])
    production_warnings = production_manifest.get("warnings", [])
    if isinstance(production_warnings, list):
        warnings.extend(str(item) for item in production_warnings)
    failures = production_manifest.get("failures", [])
    if not isinstance(failures, list):
        raise ValueError("PIPELINE_PRODUCTION_FAILURES_INVALID")

    provenance = production_manifest.get("creative_provenance", {})
    if not isinstance(provenance, dict):
        raise ValueError("PIPELINE_PROVENANCE_INVALID")

    return {
        "schema_version": "1.0",
        "return_package_id": return_package_id,
        "pipeline_run_id": run.pipeline_run_id,
        "producer": {
            "producer_id": run.producer_id,
            "producer_version": run.producer_version,
        },
        "adapter_profile": run.adapter_profile.value,
        "project_key": run.project_key,
        "packages": {
            "work": {
                "package_id": run.work_package_id,
                "source_digest": getattr(work_package, "source_digest"),
            },
            "result": {
                "package_id": run.result_package_id,
                "result_digest": getattr(result_package, "result_digest"),
                "preprocess_digest": getattr(result_package, "preprocess_digest", None),
            },
            "creative": {
                "job_id": run.creative_job_id,
                "package_id": run.creative_package_id,
                "package_digest": getattr(creative_package, "package_digest"),
            },
            "production": {
                "job_id": run.production_job_id,
                "package_id": run.production_package_id,
                "package_digest": getattr(production_package, "package_digest"),
                "plan_digest": getattr(production_package, "plan_digest"),
            },
        },
        "outputs": outputs,
        "provenance": provenance,
        "stage_summary": {
            "business": "PASS",
            "creative": "creative_ready",
            "production": "production_ready",
            "pipeline": "Completed",
        },
        "warnings": warnings,
        "failures": failures,
        "quality_outcome": "PASS",
        "completed_at": datetime.now(UTC).isoformat(),
    }
