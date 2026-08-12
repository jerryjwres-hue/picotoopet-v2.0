"""Closed paid-AI provider contracts and Worker-owned OpenAI Responses adapter."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from picotoopet_core.config.paths import RuntimePaths


class ProviderTransportAmbiguous(RuntimeError):
    """Transport ended after submit may have reached provider; never blind-retry."""


class ProviderExecutionError(RuntimeError):
    """Provider request failed without a safe accepted response."""


class DeepAiWorkerProviderConfig(BaseModel):
    """Worker-only secret/config. Endpoint and model are source-controlled, not env-overridable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_profile_id: str = "paid.reasoning.v1"
    provider_adapter_id: str = "openai.responses.v1"
    model_id: str = "gpt-5.6-terra"
    endpoint: str = "https://api.openai.com/v1/responses"
    api_key: SecretStr | None = None
    execution_enabled: bool = False

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> DeepAiWorkerProviderConfig:
        raw_enabled = environment.get("PICOTOOPET_PAID_AI_EXECUTION_ENABLED", "").strip().lower()
        enabled = raw_enabled in {"1", "true", "yes", "on"}
        raw_key = environment.get("OPENAI_API_KEY", "").strip()
        if enabled and not raw_key:
            raise ValueError("DEEP_AI_API_KEY_REQUIRED")
        return cls(
            api_key=SecretStr(raw_key) if raw_key else None,
            execution_enabled=enabled,
        )

    def redacted_dict(self) -> dict[str, object]:
        return {
            "provider_profile_id": self.provider_profile_id,
            "provider_adapter_id": self.provider_adapter_id,
            "model_id": self.model_id,
            "endpoint": self.endpoint,
            "api_key": "configured" if self.api_key is not None else "disabled",
            "execution_enabled": self.execution_enabled,
        }


class ProviderEstimate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: Decimal = Field(ge=Decimal("0"))


class ProviderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_request_id: str = Field(min_length=1, max_length=240)
    output: dict[str, Any]
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    actual_cost_usd: Decimal = Field(ge=Decimal("0"))
    cost_source: str = Field(min_length=1, max_length=80)
    structural_error: bool = False
    semantic_failure: bool = False


class PaidAiProviderAdapter(Protocol):
    def estimate(self, *, request_bytes: bytes, repair: bool) -> ProviderEstimate: ...

    def execute(
        self,
        *,
        request_bytes: bytes,
        attempt_id: str,
        repair: bool,
    ) -> ProviderResponse: ...

    def reconcile(self, attempt_id: str) -> ProviderResponse | None: ...


class DeepAiProviderRequestReader:
    """Read only immutable Core-managed sanitized request packages."""

    def __init__(self, paths: RuntimePaths) -> None:
        self.paths = paths

    def read(self, relpath: str) -> bytes:
        root = self.paths.root.resolve()
        target = (root / Path(relpath)).resolve()
        trusted = self.paths.deep_ai_requests_dir.resolve()
        if target.parent != trusted:
            raise ValueError("DEEP_AI_REQUEST_PATH_ESCAPE")
        return target.read_bytes()


@dataclass(frozen=True, slots=True)
class StoredProviderResult:
    relpath: str
    digest: str
    size_bytes: int


class DeepAiProviderResultStore:
    """Persist normalized provider responses without credentials or authorization metadata."""

    def __init__(self, paths: RuntimePaths) -> None:
        self.paths = paths
        self.paths.deep_ai_results_dir.mkdir(parents=True, exist_ok=True)

    def save(self, *, attempt_id: str, response: ProviderResponse) -> StoredProviderResult:
        payload = {
            "schema_version": "1.0",
            "attempt_id": attempt_id,
            "provider_response": response.model_dump(mode="json"),
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(canonical).hexdigest()
        target = (self.paths.deep_ai_results_dir / f"{digest}.json").resolve()
        trusted = self.paths.deep_ai_results_dir.resolve()
        if target.parent != trusted:
            raise ValueError("DEEP_AI_RESULT_PATH_ESCAPE")
        if target.exists():
            if target.read_bytes() != canonical:
                raise ValueError("DEEP_AI_RESULT_DIGEST_CONFLICT")
        else:
            temporary = target.with_suffix(".json.tmp")
            temporary.write_bytes(canonical)
            temporary.replace(target)
        return StoredProviderResult(
            relpath=target.relative_to(self.paths.root.resolve()).as_posix(),
            digest=digest,
            size_bytes=len(canonical),
        )

    def read(self, relpath: str) -> ProviderResponse:
        root = self.paths.root.resolve()
        target = (root / Path(relpath)).resolve()
        trusted = self.paths.deep_ai_results_dir.resolve()
        if target.parent != trusted:
            raise ValueError("DEEP_AI_RESULT_PATH_ESCAPE")
        payload = json.loads(target.read_text(encoding="utf-8"))
        return ProviderResponse.model_validate(payload["provider_response"])


class OpenAiResponsesPaidAiAdapter:
    """Source-closed OpenAI Responses adapter. Never exposes tools or arbitrary endpoint/model."""

    INPUT_PRICE_PER_MILLION = Decimal("2.50")
    OUTPUT_PRICE_PER_MILLION = Decimal("15.00")
    MAX_OUTPUT_TOKENS = 4000
    REPAIR_OUTPUT_TOKENS = 2000

    def __init__(self, config: DeepAiWorkerProviderConfig) -> None:
        if not config.execution_enabled or config.api_key is None:
            raise ValueError("DEEP_AI_PROVIDER_EXECUTION_DISABLED")
        self.config = config
        from openai import OpenAI

        self._client = OpenAI(
            api_key=config.api_key.get_secret_value(),
            base_url="https://api.openai.com/v1",
            timeout=120.0,
            max_retries=0,
        )

    @classmethod
    def _cost(cls, input_tokens: int, output_tokens: int) -> Decimal:
        million = Decimal(1_000_000)
        return (
            Decimal(input_tokens) * cls.INPUT_PRICE_PER_MILLION / million
            + Decimal(output_tokens) * cls.OUTPUT_PRICE_PER_MILLION / million
        ).quantize(Decimal("0.000001"))

    def estimate(self, *, request_bytes: bytes, repair: bool) -> ProviderEstimate:
        # Conservative preflight without sending data: approximate UTF-8 bytes at <=4 bytes/token,
        # plus fixed instruction overhead. Actual provider usage is recorded after the response.
        input_tokens = max(1, (len(request_bytes) + 3) // 4 + 256)
        output_tokens = self.REPAIR_OUTPUT_TOKENS if repair else self.MAX_OUTPUT_TOKENS
        return ProviderEstimate(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=self._cost(input_tokens, output_tokens),
        )

    def execute(
        self,
        *,
        request_bytes: bytes,
        attempt_id: str,
        repair: bool,
    ) -> ProviderResponse:
        instructions = (
            "Return only one JSON object matching the provided return_schema. "
            "Use only the supplied sanitized evidence and provenance. "
            "Do not propose or invoke tools, shell commands, browsing, Git/GitHub, ComfyUI, "
            "external URLs, or hidden actions."
        )
        if repair:
            instructions += " Repair structure only; preserve supported semantic content."
        max_output = self.REPAIR_OUTPUT_TOKENS if repair else self.MAX_OUTPUT_TOKENS
        try:
            response = self._client.responses.create(
                model=self.config.model_id,
                instructions=instructions,
                input=request_bytes.decode("utf-8"),
                max_output_tokens=max_output,
                store=False,
                metadata={"picotoopet_attempt_id": attempt_id},
                extra_headers={"Idempotency-Key": attempt_id},
            )
        except Exception as exc:
            # With zero automatic retries, a timeout/connection loss after submit is ambiguous.
            # The execution coordinator must reconcile or stop rather than pay for another request.
            from openai import APIConnectionError, APITimeoutError

            if isinstance(exc, (APIConnectionError, APITimeoutError)):
                raise ProviderTransportAmbiguous(str(exc)) from exc
            raise ProviderExecutionError(type(exc).__name__) from exc

        text = response.output_text or ""
        structural_error = False
        try:
            output = json.loads(text)
            if not isinstance(output, dict):
                structural_error = True
                output = {"raw_output": text}
        except json.JSONDecodeError:
            structural_error = True
            output = {"raw_output": text}
        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        return ProviderResponse(
            provider_request_id=str(response.id),
            output=output,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            actual_cost_usd=self._cost(input_tokens, output_tokens),
            cost_source="calculated:openai-gpt-5.6-terra-2026-08-11",
            structural_error=structural_error,
            semantic_failure=False,
        )

    def reconcile(self, attempt_id: str) -> ProviderResponse | None:
        # Responses API does not provide a lookup by our idempotency key. If the request ID was
        # never durably returned, exact reconciliation is not safe; caller must stop at NeedsHuman.
        del attempt_id
        return None

    def close(self) -> None:
        self._client.close()
