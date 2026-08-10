from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError

from picotoopet_core.business.local_intelligence import (
    LocalIntelligenceConfig,
    OpenAiCompatibleLocalIntelligenceAdapter,
)
from picotoopet_core.business.models import BusinessAnalysisProfile
from picotoopet_core.business.profiles import profile_definition


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/v1",
        "http://192.168.1.20:11434/v1",
        "http://example.com/v1",
        "http://user:pass@127.0.0.1:11434/v1",
    ],
)
def test_adapter_rejects_non_loopback_or_credentialed_endpoint(url: str) -> None:
    with pytest.raises(ValidationError, match="loopback"):
        LocalIntelligenceConfig(base_url=url, model_id="gpt-oss:20b")


def test_adapter_uses_trusted_model_fixed_profile_and_no_tools() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        result = {
            "schema_version": "1.0",
            "analysis_profile": "reviews.voice_of_customer.v1",
            "summary": "Supported summary.",
            "findings": [
                {
                    "rank": 1,
                    "title": "Drying time",
                    "insight": "Supported by one record.",
                    "confidence": 0.8,
                    "evidence_ids": ["reviews:row:00000000"],
                }
            ],
            "warnings": [],
            "needs_deep_ai": False,
            "needs_human": False,
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(result)}}]},
        )

    config = LocalIntelligenceConfig(
        base_url="http://127.0.0.1:11434/v1",
        model_id="gpt-oss:20b",
    )
    client = httpx.Client(base_url=config.base_url, transport=httpx.MockTransport(handler))
    adapter = OpenAiCompatibleLocalIntelligenceAdapter(config, client=client)
    try:
        result = adapter.run(
            profile_definition(BusinessAnalysisProfile.REVIEWS_VOICE_OF_CUSTOMER_V1),
            {
                "analysis_profile": "reviews.voice_of_customer.v1",
                "evidence": [
                    {"evidence_id": "reviews:row:00000000", "value": "untrusted data"}
                ],
            },
        )
    finally:
        client.close()

    assert captured["model"] == "gpt-oss:20b"
    assert "tools" not in captured
    assert "functions" not in captured
    assert captured["response_format"] == {"type": "json_object"}
    assert result["analysis_profile"] == "reviews.voice_of_customer.v1"


def test_health_never_starts_or_downloads_model() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return httpx.Response(200, json={"data": [{"id": "gpt-oss:20b"}]})

    config = LocalIntelligenceConfig()
    client = httpx.Client(base_url=config.base_url, transport=httpx.MockTransport(handler))
    adapter = OpenAiCompatibleLocalIntelligenceAdapter(config, client=client)
    try:
        assert adapter.health() is True
    finally:
        client.close()
    assert requests == ["/v1/models"]
