from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from picotoopet_core.agents.models import AgentResult
from picotoopet_core.agents.runtime import AgentRuntime


@dataclass
class FakeRunResult:
    output: object


class FakeAgent:
    def __init__(self, output: object) -> None:
        self.output = output
        self.prompts: list[str] = []

    async def run(self, prompt: str) -> FakeRunResult:
        self.prompts.append(prompt)
        return FakeRunResult(self.output)


async def test_runtime_returns_validated_structured_result() -> None:
    """Agent 输出必须被统一模型验证后返回。"""

    agent = FakeAgent(
        {
            "summary": "素材适合制作 15 秒真实宠物短视频。",
            "confidence": 0.91,
            "findings": ["主体清晰", "背景干扰较少"],
            "recommended_actions": ["生成镜头表"],
        }
    )
    runtime = AgentRuntime(agent=agent)

    result = await runtime.analyze("分析素材")

    assert isinstance(result, AgentResult)
    assert result.confidence == 0.91
    assert agent.prompts == ["分析素材"]


async def test_runtime_rejects_invalid_structured_result() -> None:
    """越界置信度不能绕过 Pydantic 校验。"""

    runtime = AgentRuntime(agent=FakeAgent({"summary": "x", "confidence": 2}))

    with pytest.raises(ValidationError):
        await runtime.analyze("分析")


def test_build_ollama_agent_uses_current_ollama_model_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """构造器必须使用官方 OllamaModel，并把 /v1 地址传给 Provider。"""

    import sys
    import types

    captured: dict[str, object] = {}

    class FakeOllamaProvider:
        """记录 Provider 初始化参数。"""

        def __init__(self, *, base_url: str) -> None:
            captured["base_url"] = base_url

    class FakeOllamaModel:
        """记录模型名称和 Provider。"""

        def __init__(self, model_name: str, *, provider: object) -> None:
            captured["model_name"] = model_name
            captured["provider"]   = provider

    class FakePydanticAgent:
        """记录传给 Agent 的模型与结构化输出类型。"""

        def __init__(self, model: object, **kwargs: object) -> None:
            captured["agent_model"]       = model
            captured["agent_output_type"] = kwargs["output_type"]

    root_module               = types.ModuleType("pydantic_ai")
    root_module.Agent         = FakePydanticAgent
    models_module             = types.ModuleType("pydantic_ai.models")
    ollama_model_module       = types.ModuleType("pydantic_ai.models.ollama")
    ollama_model_module.OllamaModel = FakeOllamaModel
    providers_module          = types.ModuleType("pydantic_ai.providers")
    ollama_provider_module    = types.ModuleType("pydantic_ai.providers.ollama")
    ollama_provider_module.OllamaProvider = FakeOllamaProvider

    monkeypatch.setitem(sys.modules, "pydantic_ai", root_module)
    monkeypatch.setitem(sys.modules, "pydantic_ai.models", models_module)
    monkeypatch.setitem(sys.modules, "pydantic_ai.models.ollama", ollama_model_module)
    monkeypatch.setitem(sys.modules, "pydantic_ai.providers", providers_module)
    monkeypatch.setitem(sys.modules, "pydantic_ai.providers.ollama", ollama_provider_module)

    runtime = __import__(
        "picotoopet_core.agents.runtime",
        fromlist=["build_ollama_agent"],
    ).build_ollama_agent(
        model_name="gpt-oss:20b",
        base_url="http://127.0.0.1:11434/v1",
    )

    assert isinstance(runtime.agent, FakePydanticAgent)
    assert captured["model_name"] == "gpt-oss:20b"
    assert captured["base_url"] == "http://127.0.0.1:11434/v1"
    assert captured["agent_output_type"] is AgentResult
