from __future__ import annotations

import importlib
import importlib.util

import pytest


def _module(name: str):  # type: ignore[no-untyped-def]
    if importlib.util.find_spec(name) is None:
        pytest.fail(f"{name} is not implemented")
    return importlib.import_module(name)


def test_valid_paid_result_passes_closed_schema_and_provenance_checks() -> None:
    module = _module("picotoopet_core.deep_ai.validation")
    validator = module.DeepAiResultValidator()
    decision = validator.validate(
        output={
            "findings": [
                {
                    "summary": "Long-hair pet owners report slower drying around dense undercoat.",
                    "evidence_refs": ["evidence:review-cluster-1"],
                }
            ]
        },
        return_schema={
            "type": "object",
            "required": ["findings"],
            "properties": {"findings": {"type": "array"}},
        },
        allowed_evidence_refs={"evidence:review-cluster-1"},
    )
    assert decision.outcome.value == "PASS"
    assert len(decision.output_digest) == 64
    assert decision.reasons == []


def test_missing_required_structure_converges_needs_human_after_paid_calls() -> None:
    module = _module("picotoopet_core.deep_ai.validation")
    decision = module.DeepAiResultValidator().validate(
        output={"notes": "wrong shape"},
        return_schema={"type": "object", "required": ["findings"]},
        allowed_evidence_refs=set(),
    )
    assert decision.outcome.value == "NEEDS_HUMAN"
    assert "DEEP_AI_RETURN_SCHEMA_INVALID" in decision.reasons


def test_forbidden_execution_authority_is_rejected() -> None:
    module = _module("picotoopet_core.deep_ai.validation")
    decision = module.DeepAiResultValidator().validate(
        output={
            "findings": [{"summary": "Run this command", "command": "powershell.exe -File x.ps1"}],
            "tools": [{"type": "shell"}],
            "endpoint": "https://evil.invalid/api",
        },
        return_schema={"type": "object", "required": ["findings"]},
        allowed_evidence_refs=set(),
    )
    assert decision.outcome.value == "REJECT"
    assert "DEEP_AI_FORBIDDEN_AUTHORITY" in decision.reasons


def test_unknown_evidence_reference_is_rejected() -> None:
    module = _module("picotoopet_core.deep_ai.validation")
    decision = module.DeepAiResultValidator().validate(
        output={
            "findings": [
                {
                    "summary": "Unsupported claim",
                    "evidence_refs": ["evidence:not-in-sanitized-package"],
                }
            ]
        },
        return_schema={"type": "object", "required": ["findings"]},
        allowed_evidence_refs={"evidence:review-cluster-1"},
    )
    assert decision.outcome.value == "REJECT"
    assert "DEEP_AI_EVIDENCE_REFERENCE_INVALID" in decision.reasons
