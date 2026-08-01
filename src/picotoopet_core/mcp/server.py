"""MCP SDK 服务器构造入口。"""

from __future__ import annotations

from typing import Any

from picotoopet_core.services import Services

from .registry import build_registry
from .tools import McpToolExecutor


def build_mcp_server(services: Services):
    """延迟导入 MCP SDK 并注册冻结工具。"""

    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - 正式安装环境验证
        raise RuntimeError("缺少 MCP Python SDK，请运行 Mac 安装器。") from exc

    server   = FastMCP("Picotoo Pet MCP Hub")
    executor = McpToolExecutor(services)
    for spec in build_registry().values():
        def handler(arguments: dict[str, Any], _tool_name: str = spec.name) -> dict[str, Any]:
            """动态工具处理器。"""

            return executor.execute(_tool_name, arguments)

        handler.__name__ = f"tool_{spec.name}"
        handler.__doc__  = spec.description
        server.tool(name=spec.name, description=spec.description)(handler)
    return server
