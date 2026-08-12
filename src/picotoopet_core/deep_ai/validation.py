"""Deterministic validation for paid-AI results before source continuation."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .models import DeepAiValidationOutcome


_FORBIDDEN_KEYS = frozenset(
    {
        "command",
        "commands",
        "shell",
        "powershell",
        "tools",
        "tool_calls",
        "tool_call",
        "endpoint",
        "url",
        "api_key",
        "provider_key",
        "workflow",
        "workflow_json",
        "node_class",
        "model_path",
        "executable",
    }
)


class DeepAiValidationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: DeepAiValidationOutcome
    reasons: list[str] = Field(default_factory=list)
    output_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class DeepAiResultValidator:
    """Closed validator: schema, evidence references, and forbidden authority."""

    @staticmethod
    def _digest(output: dict[str, Any]) -> str:
        canonical = json.dumps(
            output,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @classmethod
    def _contains_forbidden_authority(cls, value: Any) -> bool:
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).strip().lower() in _FORBIDDEN_KEYS:
                    return True
                if cls._contains_forbidden_authority(item):
                    return True
        elif isinstance(value, list):
            return any(cls._contains_forbidden_authority(item) for item in value)
        return False

    @classmethod
    def _evidence_refs(cls, value: Any) -> set[str]:
        refs: set[str] = set()
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key) == "evidence_refs" and isinstance(item, list):
                    refs.update(str(ref) for ref in item)
                refs.update(cls._evidence_refs(item))
        elif isinstance(value, list):
            for item in value:
                refs.update(cls._evidence_refs(item))
        return refs

    @staticmethod
    def _schema_valid(output: dict[str, Any], schema: dict[str, Any]) -> bool:
        if schema.get("type") == "object" and not isinstance(output, dict):
            return False
        required = schema.get("required", [])
        if isinstance(required, list) and any(str(key) not in output for key in required):
            return False
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            return True
        type_map: dict[str, type | tuple[type, ...]] = {
            "object": dict,
            "array": list,
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
        }
        for key, descriptor in properties.items():
            if key not in output or not isinstance(descriptor, dict):
                continue
            expected = type_map.get(str(descriptor.get("type")))
            if expected is not None and not isinstance(output[key], expected):
                return False
        return True

    def validate(
        self,
        *,
        output: dict[str, Any],
        return_schema: dict[str, Any],
        allowed_evidence_refs: set[str],
    ) -> DeepAiValidationDecision:
        digest = self._digest(output)
        if self._contains_forbidden_authority(output):
            return DeepAiValidationDecision(
                outcome=DeepAiValidationOutcome.REJECT,
                reasons=["DEEP_AI_FORBIDDEN_AUTHORITY"],
                output_digest=digest,
            )
        referenced = self._evidence_refs(output)
        if not referenced.issubset(allowed_evidence_refs):
            return DeepAiValidationDecision(
                outcome=DeepAiValidationOutcome.REJECT,
                reasons=["DEEP_AI_EVIDENCE_REFERENCE_INVALID"],
                output_digest=digest,
            )
        if not self._schema_valid(output, return_schema):
            return DeepAiValidationDecision(
                outcome=DeepAiValidationOutcome.NEEDS_HUMAN,
                reasons=["DEEP_AI_RETURN_SCHEMA_INVALID"],
                output_digest=digest,
            )
        return DeepAiValidationDecision(
            outcome=DeepAiValidationOutcome.PASS,
            reasons=[],
            output_digest=digest,
        )
