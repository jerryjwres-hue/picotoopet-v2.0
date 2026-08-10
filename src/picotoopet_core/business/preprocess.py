"""Deterministic preprocessing before local LLM inference."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import unicodedata
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .archive import validate_work_package_archive
from .models import BusinessAnalysisProfile, WorkPackageManifest
from .profiles import AnalysisProfileDefinition


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str
    artifact_id: str
    source_index: int
    value: dict[str, Any] | str


class AnalysisChunk(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_index: int
    context_digest: str
    evidence_ids: list[str]
    context: dict[str, Any]


class PreprocessedAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0"
    work_package_id: str
    analysis_profile: BusinessAnalysisProfile
    source_digest: str
    preprocess_digest: str
    aggregate_facts: dict[str, Any]
    evidence_records: list[EvidenceRecord]
    chunks: list[AnalysisChunk]


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest_json(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _normalize_scalar(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFKC", value.replace("\r\n", "\n").replace("\r", "\n")).strip()
    if isinstance(value, list):
        return [_normalize_scalar(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _normalize_scalar(item) for key, item in sorted(value.items(), key=lambda p: str(p[0]))}
    return value


def _parse_payload(media_type: str, raw: bytes) -> list[dict[str, Any] | str]:
    text = raw.decode("utf-8")
    if media_type == "application/json":
        value = json.loads(text)
        if isinstance(value, list):
            return [_normalize_scalar(item) for item in value]
        if isinstance(value, (dict, str)):
            return [_normalize_scalar(value)]
        return [_normalize_scalar({"value": value})]
    if media_type in {"application/jsonl", "application/x-ndjson"}:
        records: list[dict[str, Any] | str] = []
        for line in text.splitlines():
            if line.strip():
                records.append(_normalize_scalar(json.loads(line)))
        return records
    if media_type == "text/csv":
        reader = csv.DictReader(io.StringIO(text))
        return [_normalize_scalar(dict(row)) for row in reader]
    if media_type == "text/plain":
        return [_normalize_scalar(line) for line in text.splitlines() if line.strip()]
    raise ValueError("unsupported media type")


def _stable_evidence_id(
    artifact_id: str,
    source_index: int,
    value: dict[str, Any] | str,
    record_key_field: str | None,
) -> str:
    if record_key_field and isinstance(value, dict):
        candidate = value.get(record_key_field)
        if isinstance(candidate, (str, int, float)) and str(candidate).strip():
            key = unicodedata.normalize("NFKC", str(candidate)).strip()
            short = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
            return f"{artifact_id}:key:{short}"
    return f"{artifact_id}:row:{source_index:08d}"


def _even_sample(records: list[EvidenceRecord], limit: int) -> list[EvidenceRecord]:
    if len(records) <= limit:
        return records
    if limit <= 1:
        return [records[0]]
    indexes = [round(i * (len(records) - 1) / (limit - 1)) for i in range(limit)]
    return [records[index] for index in indexes]


def _aggregate(records: list[EvidenceRecord], total_records: int, duplicates: int) -> dict[str, Any]:
    rating_counts: Counter[str] = Counter()
    field_counts: Counter[str] = Counter()
    for record in records:
        if isinstance(record.value, dict):
            field_counts.update(record.value.keys())
            for key in ("rating", "stars", "score"):
                if key in record.value and record.value[key] not in {None, ""}:
                    rating_counts[str(record.value[key])] += 1
                    break
    return {
        "total_records": total_records,
        "unique_records": len(records),
        "duplicate_records": duplicates,
        "top_fields": field_counts.most_common(30),
        "rating_counts": sorted(rating_counts.items()),
    }


def preprocess_work_package(
    package_path: Path,
    profile: AnalysisProfileDefinition,
) -> PreprocessedAnalysis:
    """Build bounded stable evidence/chunks from the immutable validated archive."""

    validated = validate_work_package_archive(package_path)
    manifest: WorkPackageManifest = validated.manifest
    if manifest.analysis_profile is not profile.profile_id:
        raise ValueError("analysis profile mismatch")

    unique: list[EvidenceRecord] = []
    seen: set[str] = set()
    total_records = 0
    duplicates = 0
    with zipfile.ZipFile(validated.archive_path, "r") as archive:
        for descriptor in manifest.inputs:
            raw = archive.read(f"{validated.top_level}/{descriptor.path}")
            records = _parse_payload(descriptor.media_type, raw)
            for source_index, value in enumerate(records):
                total_records += 1
                normalized = _normalize_scalar(value)
                canonical = _canonical(normalized)
                duplicate_key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
                if duplicate_key in seen:
                    duplicates += 1
                    continue
                seen.add(duplicate_key)
                unique.append(
                    EvidenceRecord(
                        evidence_id=_stable_evidence_id(
                            descriptor.artifact_id,
                            source_index,
                            normalized,
                            descriptor.record_key_field,
                        ),
                        artifact_id=descriptor.artifact_id,
                        source_index=source_index,
                        value=normalized,
                    )
                )

    if not unique:
        raise ValueError("business package contains no usable records")
    sampled = _even_sample(unique, profile.evidence_record_limit)
    aggregate_facts = _aggregate(unique, total_records, duplicates)
    chunk_count = math.ceil(len(sampled) / profile.chunk_record_limit)
    chunks: list[AnalysisChunk] = []
    for chunk_index in range(chunk_count):
        start = chunk_index * profile.chunk_record_limit
        selected = sampled[start : start + profile.chunk_record_limit]
        context = {
            "schema_version": "1.0",
            "analysis_profile": profile.profile_id.value,
            "objective": manifest.objective,
            "aggregate_facts": aggregate_facts,
            "chunk_index": chunk_index,
            "chunk_count": chunk_count,
            "evidence": [record.model_dump(mode="json") for record in selected],
        }
        chunks.append(
            AnalysisChunk(
                chunk_index=chunk_index,
                context_digest=_digest_json(context),
                evidence_ids=[record.evidence_id for record in selected],
                context=context,
            )
        )

    digest_payload = {
        "package_id": manifest.package_id,
        "analysis_profile": manifest.analysis_profile.value,
        "source_digest": validated.source_digest,
        "aggregate_facts": aggregate_facts,
        "evidence": [record.model_dump(mode="json") for record in sampled],
        "chunks": [chunk.context_digest for chunk in chunks],
    }
    return PreprocessedAnalysis(
        work_package_id=manifest.package_id,
        analysis_profile=manifest.analysis_profile,
        source_digest=validated.source_digest,
        preprocess_digest=_digest_json(digest_payload),
        aggregate_facts=aggregate_facts,
        evidence_records=sampled,
        chunks=chunks,
    )
