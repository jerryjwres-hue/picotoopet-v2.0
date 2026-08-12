"""Closed trusted policy for paid-AI escalation."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class DeepAiProviderProfile(BaseModel):
    """Trusted provider identity and bounded cost envelope frozen before approval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_profile_id: str
    provider_adapter_id: str
    model_id: str
    request_format_version: str
    response_format_version: str
    pricing_version: str
    max_input_tokens: int = Field(ge=1)
    max_output_tokens: int = Field(ge=1)
    max_calls: int = Field(ge=1, le=2)
    max_cost_usd: Decimal = Field(ge=Decimal("0"))
    execution_enabled: bool = False

    @property
    def provider_profile_digest(self) -> str:
        payload = self.model_dump(mode="json")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class DeepAiEscalationPolicy:
    """Source-controlled mapping from eligible semantic stages to one trusted profile."""

    POLICY_VERSION = "deep-ai.escalation.v1"
    _ELIGIBLE_SOURCE_KINDS = frozenset(
        {
            "business.local_intelligence",
            "creative.intelligence",
        }
    )

    def __init__(self, profile: DeepAiProviderProfile) -> None:
        self._profile = profile

    @classmethod
    def default(cls) -> DeepAiEscalationPolicy:
        return cls(
            DeepAiProviderProfile(
                provider_profile_id="paid.reasoning.v1",
                provider_adapter_id="paid.reasoning.api.v1",
                model_id="trusted-reasoning-model",
                request_format_version="deep-ai.request.v1",
                response_format_version="deep-ai.response.v1",
                pricing_version="pricing.placeholder.v1",
                max_input_tokens=12000,
                max_output_tokens=4000,
                max_calls=2,
                max_cost_usd=Decimal("3.50"),
                execution_enabled=False,
            )
        )

    @property
    def policy_version(self) -> str:
        return self.POLICY_VERSION

    def for_source(self, source_kind: str) -> DeepAiProviderProfile:
        if source_kind not in self._ELIGIBLE_SOURCE_KINDS:
            raise ValueError("DEEP_AI_SOURCE_NOT_ELIGIBLE")
        return self._profile
