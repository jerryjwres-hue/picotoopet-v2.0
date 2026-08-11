"""Normalize validated 2.3.18.1 Result Packages into stable creative sources."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from picotoopet_core.db.database import Database

from .models import CreativeEligibleSourceRecord


class CreativeSourceError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CreativeSourceFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_finding_ref: str
    result_package_id: str
    result_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    work_package_id: str
    finding_rank: int = Field(ge=1, le=100)
    finding_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    finding: dict[str, Any]
    evidence_ids: list[str] = Field(min_length=1, max_length=50)


class NormalizedCreativeSourceSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    result_package_ids: list[str]
    result_digests: list[str]
    findings: list[CreativeSourceFinding]
    evidence_ids: list[str]
    source_set_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class CreativeSourceNormalizer:
    """Read only PASS/Completed business results and derive immutable finding refs."""

    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _canonical(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @classmethod
    def _digest(cls, value: object) -> str:
        return hashlib.sha256(cls._canonical(value).encode("utf-8")).hexdigest()

    def normalize_source_set(self, result_package_ids: list[str]) -> NormalizedCreativeSourceSet:
        if not 1 <= len(result_package_ids) <= 8 or len(set(result_package_ids)) != len(result_package_ids):
            raise CreativeSourceError("SOURCE_COUNT_INVALID")
        rows = []
        for result_id in sorted(result_package_ids):
            row = self.database.fetchone(
                "SELECT r.*, w.project_key, w.status AS work_status "
                "FROM business_result_packages r JOIN business_work_packages w "
                "ON w.work_package_id=r.work_package_id WHERE r.result_package_id=?",
                (result_id,),
            )
            if row is None:
                raise CreativeSourceError("SOURCE_RESULT_NOT_FOUND")
            if row["quality_outcome"] != "PASS":
                raise CreativeSourceError("SOURCE_NOT_PASS")
            if row["work_status"] != "Completed":
                raise CreativeSourceError("SOURCE_WORK_NOT_COMPLETED")
            rows.append(row)
        projects = {str(row["project_key"]) for row in rows}
        if len(projects) != 1:
            raise CreativeSourceError("SOURCE_PROJECT_MISMATCH")
        project_key = next(iter(projects))

        findings: list[CreativeSourceFinding] = []
        result_digests: list[str] = []
        for row in rows:
            result_id = str(row["result_package_id"])
            result_digest = str(row["result_digest"])
            result_digests.append(result_digest)
            try:
                payload = json.loads(row["result_json"])
                raw_findings = payload["findings"]
            except (json.JSONDecodeError, KeyError, TypeError) as error:
                raise CreativeSourceError("SOURCE_RESULT_INVALID") from error
            if not isinstance(raw_findings, list) or not raw_findings:
                raise CreativeSourceError("SOURCE_FINDINGS_MISSING")
            ranks = [item.get("rank") if isinstance(item, dict) else None for item in raw_findings]
            if ranks != list(range(1, len(raw_findings) + 1)):
                raise CreativeSourceError("SOURCE_FINDING_RANK_INVALID")
            for raw in raw_findings:
                if not isinstance(raw, dict):
                    raise CreativeSourceError("SOURCE_FINDING_INVALID")
                evidence_ids = raw.get("evidence_ids")
                if (
                    not isinstance(evidence_ids, list)
                    or not evidence_ids
                    or any(not isinstance(item, str) or not item for item in evidence_ids)
                ):
                    raise CreativeSourceError("SOURCE_EVIDENCE_INVALID")
                rank = int(raw["rank"])
                findings.append(
                    CreativeSourceFinding(
                        source_finding_ref=f"{result_id}:finding:{rank}",
                        result_package_id=result_id,
                        result_digest=result_digest,
                        work_package_id=str(row["work_package_id"]),
                        finding_rank=rank,
                        finding_digest=self._digest(raw),
                        finding=raw,
                        evidence_ids=list(evidence_ids),
                    )
                )
        evidence_ids = sorted({item for finding in findings for item in finding.evidence_ids})
        source_payload = {
            "project_key": project_key,
            "results": [
                {"result_package_id": str(row["result_package_id"]), "result_digest": str(row["result_digest"])}
                for row in rows
            ],
            "findings": [
                {
                    "source_finding_ref": finding.source_finding_ref,
                    "finding_digest": finding.finding_digest,
                    "evidence_ids": finding.evidence_ids,
                }
                for finding in findings
            ],
        }
        return NormalizedCreativeSourceSet(
            project_key=project_key,
            result_package_ids=[str(row["result_package_id"]) for row in rows],
            result_digests=result_digests,
            findings=findings,
            evidence_ids=evidence_ids,
            source_set_digest=self._digest(source_payload),
        )

    def persist_source_set(self, creative_job_id: str, source_set: NormalizedCreativeSourceSet) -> None:
        now = self.database.scalar("SELECT created_at FROM creative_jobs WHERE creative_job_id=?", (creative_job_id,))
        if now is None:
            raise KeyError(creative_job_id)
        with self.database.transaction() as connection:
            for result_id, result_digest in zip(
                source_set.result_package_ids,
                source_set.result_digests,
                strict=True,
            ):
                row = connection.execute(
                    "SELECT work_package_id FROM business_result_packages WHERE result_package_id=?",
                    (result_id,),
                ).fetchone()
                if row is None:
                    raise CreativeSourceError("SOURCE_RESULT_NOT_FOUND")
                connection.execute(
                    "INSERT OR IGNORE INTO creative_job_sources("
                    "creative_job_id,result_package_id,result_digest,source_work_package_id,project_key,created_at"
                    ") VALUES (?,?,?,?,?,?)",
                    (
                        creative_job_id,
                        result_id,
                        result_digest,
                        row["work_package_id"],
                        source_set.project_key,
                        now,
                    ),
                )
            for finding in source_set.findings:
                connection.execute(
                    "INSERT OR IGNORE INTO creative_source_findings("
                    "creative_job_id,source_finding_ref,result_package_id,finding_rank,finding_digest,"
                    "finding_json,evidence_ids_json,created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        creative_job_id,
                        finding.source_finding_ref,
                        finding.result_package_id,
                        finding.finding_rank,
                        finding.finding_digest,
                        self._canonical(finding.finding),
                        self._canonical(finding.evidence_ids),
                        now,
                    ),
                )

    def load_persisted_source_set(self, creative_job_id: str) -> NormalizedCreativeSourceSet:
        job = self.database.fetchone(
            "SELECT project_key,source_set_digest FROM creative_jobs WHERE creative_job_id=?",
            (creative_job_id,),
        )
        if job is None:
            raise KeyError(creative_job_id)
        source_rows = self.database.fetchall(
            "SELECT result_package_id,result_digest,source_work_package_id FROM creative_job_sources "
            "WHERE creative_job_id=? ORDER BY result_package_id",
            (creative_job_id,),
        )
        finding_rows = self.database.fetchall(
            "SELECT * FROM creative_source_findings WHERE creative_job_id=? "
            "ORDER BY result_package_id,finding_rank",
            (creative_job_id,),
        )
        findings = [
            CreativeSourceFinding(
                source_finding_ref=row["source_finding_ref"],
                result_package_id=row["result_package_id"],
                result_digest=next(
                    source["result_digest"]
                    for source in source_rows
                    if source["result_package_id"] == row["result_package_id"]
                ),
                work_package_id=next(
                    source["source_work_package_id"]
                    for source in source_rows
                    if source["result_package_id"] == row["result_package_id"]
                ),
                finding_rank=row["finding_rank"],
                finding_digest=row["finding_digest"],
                finding=json.loads(row["finding_json"]),
                evidence_ids=json.loads(row["evidence_ids_json"]),
            )
            for row in finding_rows
        ]
        return NormalizedCreativeSourceSet(
            project_key=job["project_key"],
            result_package_ids=[row["result_package_id"] for row in source_rows],
            result_digests=[row["result_digest"] for row in source_rows],
            findings=findings,
            evidence_ids=sorted({item for finding in findings for item in finding.evidence_ids}),
            source_set_digest=job["source_set_digest"],
        )

    def list_eligible_sources(self, *, limit: int = 200) -> list[CreativeEligibleSourceRecord]:
        rows = self.database.fetchall(
            "SELECT r.result_package_id,r.work_package_id,w.project_key,r.analysis_profile,"
            "r.result_digest,r.result_json,r.created_at FROM business_result_packages r "
            "JOIN business_work_packages w ON w.work_package_id=r.work_package_id "
            "WHERE r.quality_outcome='PASS' AND w.status='Completed' "
            "ORDER BY r.created_at DESC LIMIT ?",
            (max(1, min(limit, 200)),),
        )
        records = []
        for row in rows:
            try:
                summary = str(json.loads(row["result_json"]).get("summary", ""))[:1000]
            except (json.JSONDecodeError, TypeError):
                continue
            records.append(
                CreativeEligibleSourceRecord(
                    result_package_id=row["result_package_id"],
                    work_package_id=row["work_package_id"],
                    project_key=row["project_key"],
                    analysis_profile=row["analysis_profile"],
                    result_digest=row["result_digest"],
                    summary=summary,
                    created_at=row["created_at"],
                )
            )
        return records
