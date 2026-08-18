"""Deterministic evidence-grounded handoff packages for user-operated Web GPT.

The builder exports only curated Goal/analysis/evidence facts from Mac-managed
memory. It never reads arbitrary source paths, never automates a consumer Web
GPT session, and rejects credential-like fields before any ZIP is written.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import tempfile
import zipfile
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from picotoopet_core.config.paths import RuntimePaths

from .models import GoalRecord


PROMPT_VERSION = "web-gpt-master-v1.0"
_PROMPT_RESOURCE = "web_gpt_master_v1.txt"
_MAX_PACKAGE_TEXT_CHARS = 400_000
_CREDENTIAL_KEY_PARTS = (
    "api_token",
    "token",
    "secret",
    "password",
    "credential",
    "authorization",
    "cookie",
    "session_key",
    "private_key",
)
_LOCAL_PATH_KEYS = (
    "local_path",
    "source_path",
    "file_path",
    "filesystem_path",
    "workspace_root",
)
_WINDOWS_PATH = re.compile(r"^[A-Za-z]:[\\/]")


class HandoffSafetyError(RuntimeError):
    """Curated handoff input violated a fixed safety/traceability boundary."""


class WebGptHandoffBuilder:
    """Build one compact deterministic ZIP for manual use in Web GPT."""

    def __init__(
        self,
        paths: RuntimePaths,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.paths = paths
        self.root = paths.autonomous_handoffs_dir.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._clock = clock or (lambda: datetime.now(UTC))

    def build(
        self,
        *,
        goal: GoalRecord,
        analysis: Mapping[str, Any],
        evidence: Sequence[Mapping[str, Any]],
        sources: Sequence[Mapping[str, Any]],
        creative_brief: Mapping[str, Any],
    ) -> Path:
        """Validate curated inputs and atomically write a reproducible handoff ZIP."""

        goal_payload = goal.model_dump(mode="json")
        analysis_payload = dict(analysis)
        evidence_payload = [dict(item) for item in evidence]
        sources_payload = [dict(item) for item in sources]
        creative_payload = dict(creative_brief)

        self._assert_safe_payload(goal_payload)
        self._assert_safe_payload(analysis_payload)
        self._assert_safe_payload(evidence_payload)
        self._assert_safe_payload(sources_payload)
        self._assert_safe_payload(creative_payload)

        source_ids = self._validate_sources(sources_payload)
        evidence_ids = self._validate_evidence(evidence_payload, source_ids=source_ids)
        self._validate_fact_links(analysis_payload, evidence_ids=evidence_ids)

        ordered_sources = sorted(sources_payload, key=lambda item: str(item["source_id"]))
        ordered_evidence = sorted(evidence_payload, key=lambda item: str(item["evidence_id"]))
        prompt = self._load_fixed_prompt()
        created_at = self._now().isoformat()

        package_files = self._build_files(
            goal=goal,
            goal_payload=goal_payload,
            analysis=analysis_payload,
            evidence=ordered_evidence,
            sources=ordered_sources,
            creative_brief=creative_payload,
            prompt=prompt,
        )
        file_sha256 = {
            name: hashlib.sha256(data).hexdigest()
            for name, data in sorted(package_files.items())
        }
        manifest = {
            "schema_version": "1.0",
            "handoff_type": "web-gpt-production",
            "prompt_version": PROMPT_VERSION,
            "goal_id": goal.goal_id,
            "created_at": created_at,
            "evidence_ids": sorted(evidence_ids),
            "source_ids": sorted(source_ids),
            "file_sha256": file_sha256,
        }
        package_files["HANDOFF_MANIFEST.json"] = self._json_bytes(manifest)

        zip_bytes = self._zip_bytes(package_files)
        package_digest = hashlib.sha256(zip_bytes).hexdigest()
        safe_goal_id = self._safe_filename(goal.goal_id)
        destination = self.root / f"{safe_goal_id}-{package_digest[:16]}.zip"
        self._write_atomic(destination, zip_bytes)
        if hashlib.sha256(destination.read_bytes()).hexdigest() != package_digest:
            raise HandoffSafetyError("handoff ZIP verification failed")
        return destination

    def _build_files(
        self,
        *,
        goal: GoalRecord,
        goal_payload: dict[str, Any],
        analysis: dict[str, Any],
        evidence: list[dict[str, Any]],
        sources: list[dict[str, Any]],
        creative_brief: dict[str, Any],
        prompt: str,
    ) -> dict[str, bytes]:
        executive_summary = str(analysis.get("executive_summary", "")).strip()
        validated_facts = analysis.get("validated_facts", [])
        audience_insights = analysis.get("audience_insights", [])
        content_patterns = analysis.get("content_patterns", [])
        opportunities = analysis.get("opportunities", [])

        files_payload: dict[str, bytes] = {
            "00_README_直接拖给GPT.md": self._text_bytes(
                "# PicotooPet AI Web GPT 交接包\n\n"
                "把整个 ZIP 交给网页 GPT，并要求它严格执行 `WEB_GPT_MASTER_PROMPT.txt`。\n\n"
                f"- Goal ID: `{goal.goal_id}`\n"
                f"- Goal: {goal.objective}\n"
                f"- Prompt: `{PROMPT_VERSION}`\n"
                "- 数据已经由 Mac 后台整理；不要把创意描述误写成已验证事实。\n"
            ),
            "01_GOAL.json": self._json_bytes(goal_payload),
            "02_EXECUTIVE_BRIEF.md": self._text_bytes(
                "# Executive Brief\n\n" + (executive_summary or "未提供额外执行摘要。") + "\n"
            ),
            "03_VALIDATED_FACTS.json": self._json_bytes({"facts": validated_facts}),
            "04_EVIDENCE.md": self._render_evidence(evidence),
            "05_SOURCE_MANIFEST.json": self._json_bytes({"sources": sources}),
            "06_AUDIENCE_INSIGHTS.md": self._render_list(
                "Audience Insights", audience_insights
            ),
            "07_CONTENT_PATTERNS.md": self._render_list(
                "Content Patterns", content_patterns
            ),
            "08_OPPORTUNITIES.md": self._render_list("Opportunities", opportunities),
            "09_CREATIVE_BRIEF.md": self._text_bytes(
                "# Creative Brief\n\n```json\n"
                + self._json_text(creative_brief, pretty=True)
                + "\n```\n"
            ),
            "10_CONSTRAINTS.md": self._text_bytes(
                "# Constraints\n\n```json\n"
                + self._json_text(goal.constraints, pretty=True)
                + "\n```\n"
            ),
            "WEB_GPT_MASTER_PROMPT.txt": self._text_bytes(prompt),
        }
        total_chars = sum(len(value.decode("utf-8")) for value in files_payload.values())
        if total_chars > _MAX_PACKAGE_TEXT_CHARS:
            raise HandoffSafetyError("curated handoff exceeds bounded text size")
        return files_payload

    @staticmethod
    def _render_evidence(evidence: list[dict[str, Any]]) -> bytes:
        lines = ["# Evidence", ""]
        for item in evidence:
            evidence_id = str(item["evidence_id"])
            source_id = str(item["source_id"])
            text = str(item.get("text", "")).strip()
            lines.extend(
                [
                    f"## {evidence_id}",
                    f"- source_id: `{source_id}`",
                    "",
                    text or "（无额外证据文本）",
                    "",
                ]
            )
        return ("\n".join(lines).rstrip() + "\n").encode("utf-8")

    @classmethod
    def _render_list(cls, title: str, values: Any) -> bytes:
        if not isinstance(values, list):
            values = [values] if values not in (None, "") else []
        lines = [f"# {title}", ""]
        for value in values:
            if isinstance(value, (dict, list)):
                rendered = cls._json_text(value, pretty=False)
            else:
                rendered = str(value)
            lines.append(f"- {rendered}")
        if len(lines) == 2:
            lines.append("- 暂无")
        return ("\n".join(lines) + "\n").encode("utf-8")

    @staticmethod
    def _validate_sources(sources: list[dict[str, Any]]) -> set[str]:
        source_ids: set[str] = set()
        for item in sources:
            source_id = item.get("source_id")
            if not isinstance(source_id, str) or not source_id or len(source_id) > 128:
                raise HandoffSafetyError("source_id must be a bounded string")
            if source_id in source_ids:
                raise HandoffSafetyError("duplicate source_id")
            source_ids.add(source_id)
            url = item.get("url")
            if url is not None:
                if not isinstance(url, str):
                    raise HandoffSafetyError("source URL must be a string")
                parsed = urlparse(url)
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    raise HandoffSafetyError("source URL must be http(s)")
        return source_ids

    @staticmethod
    def _validate_evidence(
        evidence: list[dict[str, Any]], *, source_ids: set[str]
    ) -> set[str]:
        evidence_ids: set[str] = set()
        for item in evidence:
            evidence_id = item.get("evidence_id")
            source_id = item.get("source_id")
            if not isinstance(evidence_id, str) or not evidence_id or len(evidence_id) > 128:
                raise HandoffSafetyError("evidence_id must be a bounded string")
            if evidence_id in evidence_ids:
                raise HandoffSafetyError("duplicate evidence_id")
            if not isinstance(source_id, str) or source_id not in source_ids:
                raise HandoffSafetyError(f"unknown source_id for evidence {evidence_id}")
            evidence_ids.add(evidence_id)
        return evidence_ids

    @staticmethod
    def _validate_fact_links(analysis: dict[str, Any], *, evidence_ids: set[str]) -> None:
        facts = analysis.get("validated_facts", [])
        if not isinstance(facts, list):
            raise HandoffSafetyError("validated_facts must be a list")
        for fact in facts:
            if not isinstance(fact, Mapping):
                raise HandoffSafetyError("validated fact must be an object")
            linked = fact.get("evidence_ids", [])
            if not isinstance(linked, list):
                raise HandoffSafetyError("validated fact evidence_ids must be a list")
            for evidence_id in linked:
                if evidence_id not in evidence_ids:
                    raise HandoffSafetyError("validated fact references unknown evidence_id")

    @classmethod
    def _assert_safe_payload(cls, value: Any, *, key_path: str = "root") -> None:
        if isinstance(value, Mapping):
            for raw_key, child in value.items():
                key = str(raw_key).lower()
                if key in _LOCAL_PATH_KEYS or key.endswith("_local_path"):
                    raise HandoffSafetyError(f"local path field is forbidden: {key_path}.{key}")
                if any(part in key for part in _CREDENTIAL_KEY_PARTS):
                    raise HandoffSafetyError(f"credential field is forbidden: {key_path}.{key}")
                cls._assert_safe_payload(child, key_path=f"{key_path}.{key}")
            return
        if isinstance(value, (list, tuple)):
            for index, child in enumerate(value):
                cls._assert_safe_payload(child, key_path=f"{key_path}[{index}]")
            return
        if isinstance(value, str):
            stripped = value.strip()
            lower = stripped.lower()
            if lower.startswith(("http://", "https://")):
                return
            if cls._looks_like_local_path(stripped):
                raise HandoffSafetyError(f"local path is forbidden at {key_path}")
            if "authorization: bearer" in lower:
                raise HandoffSafetyError(f"credential text is forbidden at {key_path}")

    @staticmethod
    def _looks_like_local_path(value: str) -> bool:
        return bool(
            _WINDOWS_PATH.match(value)
            or value.startswith(("/Users/", "/private/", "/home/", "~/", "file://", "\\\\"))
        )

    @staticmethod
    def _load_fixed_prompt() -> str:
        resource = files("picotoopet_core.autonomous.prompts").joinpath(_PROMPT_RESOURCE)
        prompt = resource.read_text(encoding="utf-8")
        if f"Prompt-Version: {PROMPT_VERSION}" not in prompt:
            raise HandoffSafetyError("fixed prompt version mismatch")
        return prompt

    @staticmethod
    def _json_text(value: Any, *, pretty: bool) -> str:
        if pretty:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @classmethod
    def _json_bytes(cls, value: Any) -> bytes:
        return (cls._json_text(value, pretty=True) + "\n").encode("utf-8")

    @staticmethod
    def _text_bytes(value: str) -> bytes:
        return value.encode("utf-8")

    @staticmethod
    def _safe_filename(value: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
        return normalized[:80] or "handoff"

    @staticmethod
    def _zip_bytes(package_files: Mapping[str, bytes]) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(
            buffer,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for name in sorted(package_files):
                info = zipfile.ZipInfo(filename=name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, package_files[name], compress_type=zipfile.ZIP_DEFLATED)
        return buffer.getvalue()

    def _write_atomic(self, destination: Path, data: bytes) -> None:
        if destination.parent.resolve() != self.root:
            raise HandoffSafetyError("handoff destination escaped managed root")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".handoff-", suffix=".partial", dir=self.root
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
