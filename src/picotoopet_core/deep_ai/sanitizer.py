"""Deterministic construction of bounded, sanitized paid-AI request packages."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


_SECRET_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{6,}\b"),
    re.compile(r"(?i)\b(?:api[_-]?key|token|password)\s*[:=]\s*[^\s,;]+"),
)
_URL_PATTERN = re.compile(r"https?://[^\s,;]+", re.IGNORECASE)
_UNIX_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.-])/(?:Users|home|private|tmp|var|Volumes)(?:/[^\s,;]+)+"
)
_WINDOWS_PATH_PATTERN = re.compile(r"\b[A-Za-z]:\\(?:[^\\\s,;]+\\)*[^\\\s,;]+")


class DeepAiSourceContext(BaseModel):
    """Trusted source facts used by the sanitizer; no arbitrary execution configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_kind: str = Field(min_length=1, max_length=120)
    source_id: str = Field(min_length=1, max_length=200)
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    project_key: str = Field(min_length=1, max_length=160)
    source_profile: str = Field(min_length=1, max_length=160)
    quality_outcome: str = Field(min_length=1, max_length=80)
    quality_reasons: list[str] = Field(default_factory=list, max_length=20)
    evidence_snippets: list[str] = Field(default_factory=list, max_length=32)
    local_result_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    return_schema: dict[str, Any]
    manual_handoff_id: str | None = Field(default=None, max_length=200)
    manual_handoff_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class DeepAiSanitizedPackage:
    canonical_bytes: bytes
    digest: str


class DeepAiSanitizer:
    """Builds one canonical JSON package from trusted facts and redacts free text."""

    SCHEMA_VERSION = "1.0"
    SANITIZER_VERSION = "deep-ai.sanitizer.v1"
    INSTRUCTION_TEMPLATE_ID = "deep-ai.reasoning.v1"
    _MAX_TEXT_CHARS = 4000
    _MAX_PACKAGE_BYTES = 64 * 1024

    @classmethod
    def _sanitize_text(cls, value: str) -> str:
        text = value[: cls._MAX_TEXT_CHARS]
        for pattern in _SECRET_PATTERNS:
            text = pattern.sub("[REDACTED_SECRET]", text)
        text = _WINDOWS_PATH_PATTERN.sub("[REDACTED_PATH]", text)
        text = _UNIX_PATH_PATTERN.sub("[REDACTED_PATH]", text)
        text = _URL_PATTERN.sub("[REDACTED_URL]", text)
        return text

    @classmethod
    def _sanitize_json(cls, value: Any) -> Any:
        if isinstance(value, str):
            return cls._sanitize_text(value)
        if isinstance(value, list):
            return [cls._sanitize_json(item) for item in value]
        if isinstance(value, dict):
            return {str(key): cls._sanitize_json(item) for key, item in value.items()}
        if value is None or isinstance(value, bool | int | float):
            return value
        return cls._sanitize_text(str(value))

    def build(self, context: DeepAiSourceContext) -> DeepAiSanitizedPackage:
        payload: dict[str, Any] = {
            "schema_version": self.SCHEMA_VERSION,
            "sanitizer_version": self.SANITIZER_VERSION,
            "instruction_template_id": self.INSTRUCTION_TEMPLATE_ID,
            "source": {
                "source_kind": context.source_kind,
                "source_id": context.source_id,
                "source_digest": context.source_digest,
                "project_key": context.project_key,
                "source_profile": context.source_profile,
                "local_result_digest": context.local_result_digest,
            },
            "quality": {
                "outcome": context.quality_outcome,
                "reasons": [self._sanitize_text(item) for item in context.quality_reasons],
            },
            "evidence_snippets": [
                self._sanitize_text(item) for item in context.evidence_snippets
            ],
            "return_schema": self._sanitize_json(context.return_schema),
            "manual_handoff": (
                {
                    "handoff_id": context.manual_handoff_id,
                    "package_digest": context.manual_handoff_digest,
                }
                if context.manual_handoff_id is not None
                else None
            ),
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(canonical) > self._MAX_PACKAGE_BYTES:
            raise ValueError("DEEP_AI_SANITIZED_PACKAGE_TOO_LARGE")
        return DeepAiSanitizedPackage(
            canonical_bytes=canonical,
            digest=hashlib.sha256(canonical).hexdigest(),
        )
