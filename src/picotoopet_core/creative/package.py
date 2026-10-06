"""Shared canonical Creative Package construction."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from .models import CreativePackageRecord, CreativeQualityOutcome
from .profiles import CreativeProfileDefinition
from .repository import CreativeRepository
from .source import NormalizedCreativeSourceSet
from .store import CreativeArtifactStore


class CreativePackageFinalizer:
    """Build and persist a PASS package through the canonical Creative path."""

    def __init__(self, *, repository: CreativeRepository, store: CreativeArtifactStore) -> None:
        self.repository = repository
        self.store = store

    def finalize(
        self,
        *,
        creative_job_id: str,
        source_set: NormalizedCreativeSourceSet,
        stage_results: dict[str, dict[str, Any]],
        profile: CreativeProfileDefinition,
        configured_model_id: str,
        package_id: str | None = None,
        completed_at: datetime | None = None,
        external_provenance: dict[str, Any] | None = None,
    ) -> CreativePackageRecord:
        package_id = package_id or str(uuid4())
        completed_at = completed_at or datetime.now(UTC)
        payload: dict[str, Any] = {
            "schema_version": "1.0",
            "creative_package_id": package_id,
            "creative_job_id": creative_job_id,
            "project_key": source_set.project_key,
            "creative_profile": profile.profile_id,
            "source_result_packages": [
                {"result_package_id": item, "result_digest": digest}
                for item, digest in zip(
                    source_set.result_package_ids,
                    source_set.result_digests,
                    strict=True,
                )
            ],
            "source_set_digest": source_set.source_set_digest,
            "source_findings": [
                {
                    "source_finding_ref": item.source_finding_ref,
                    "finding_digest": item.finding_digest,
                    "evidence_ids": item.evidence_ids,
                }
                for item in source_set.findings
            ],
            "configured_model_id": configured_model_id,
            "stage_template_versions": {
                stage.stage_kind.value: stage.template_version for stage in profile.stages
            },
            "stage_results": stage_results,
            "quality_outcome": CreativeQualityOutcome.PASS.value,
            "completed_at": completed_at.isoformat(),
        }
        if external_provenance is not None:
            payload["external_provenance"] = external_provenance
        relative, package_digest = self.store.write_creative_package(package_id, payload)
        return self.repository.save_package(
            CreativePackageRecord(
                creative_package_id=package_id,
                creative_job_id=creative_job_id,
                source_set_digest=source_set.source_set_digest,
                package_digest=package_digest,
                package_relpath=relative,
                manifest=payload,
                quality_outcome=CreativeQualityOutcome.PASS,
                created_at=completed_at,
            )
        )
