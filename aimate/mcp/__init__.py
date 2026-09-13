"""内网 MCP 工具库（信创 · 纯 stdlib）。

- registry: McpRegistry（多 server 管理）+ StdioMcpClient（JSON-RPC 2.0 client）
- demo: 一个本地 stdio MCP server 示例（.py 自带的工具，供自测与接线演示）
"""
from aimate.mcp.registry import McpError, McpRegistry, StdioMcpClient

__all__ = ["McpError", "McpRegistry", "StdioMcpClient"]
