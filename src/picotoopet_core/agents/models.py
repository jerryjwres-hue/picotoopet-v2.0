"""Agent 结构化输出模型。"""

from pydantic import BaseModel, Field


class AgentResult(BaseModel):
    """Mac Core 统一分析结果。"""

    summary: str = Field(min_length=1)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    findings: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
