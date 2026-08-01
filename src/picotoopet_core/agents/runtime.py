"""可测试、延迟加载 PydanticAI 的 Agent Runtime。"""

from __future__ import annotations

from typing import Any, Protocol

from .models import AgentResult


class AgentLike(Protocol):
    """运行时仅依赖的最小 Agent 接口。"""

    async def run(self, prompt: str) -> Any:
        """执行一次结构化分析。"""


class AgentRuntime:
    """把 Agent 输出统一转换为受验证的 AgentResult。"""

    def __init__(self, agent: AgentLike) -> None:
        self.agent = agent

    async def analyze(self, prompt: str) -> AgentResult:
        """运行分析并拒绝不符合契约的输出。"""

        response = await self.agent.run(prompt)
        output   = response.output
        if isinstance(output, AgentResult):
            return output
        return AgentResult.model_validate(output)


def build_ollama_agent(
    *,
    model_name: str = "gpt-oss:20b",
    base_url: str = "http://127.0.0.1:11434/v1",
) -> AgentRuntime:
    """按冻结配置构造 PydanticAI Ollama Agent。"""

    try:
        from pydantic_ai import Agent
        from pydantic_ai.models.ollama import OllamaModel
        from pydantic_ai.providers.ollama import OllamaProvider
    except ImportError as exc:  # pragma: no cover - 安装器会补齐正式依赖
        raise RuntimeError("缺少 pydantic-ai-slim 依赖，请运行 Mac 安装器。") from exc

    provider = OllamaProvider(base_url=base_url)
    model    = OllamaModel(model_name, provider=provider)
    agent    = Agent(
        model,
        output_type=AgentResult,
        system_prompt=(
            "你是 Picotoo Pet 本地分析代理。只使用已授权的数据和工具；"
            "输出简洁、可验证的结构化结论。"
        ),
    )
    return AgentRuntime(agent=agent)
