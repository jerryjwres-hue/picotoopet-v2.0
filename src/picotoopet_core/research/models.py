"""Research Gateway 2.3.27.1 的固定搜索请求与结果合同。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ResearchSearchRequest(BaseModel):
    """Windows/Core 可创建的唯一基础网络调研请求。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=20)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        # 输入边界：去除首尾空白后仍必须有内容，禁止空查询占用 Worker。
        normalized = value.strip()
        if not normalized:
            raise ValueError("query must not be blank")
        return normalized


class ResearchSearchResult(BaseModel):
    """Mac Worker 写入现有 ResultStore 的受限搜索结果。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    capability: Literal["research.search"] = "research.search"
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(ge=1, le=20)
    output: str = Field(max_length=49_152)
