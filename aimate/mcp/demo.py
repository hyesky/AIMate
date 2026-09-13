"""本地 stdio MCP server 示例（纯 stdlib · 信创，数据不出域）。

演示 AIMate 数字员工如何通过 McpRegistry 对接一个标准 MCP server：
暴露几个示例工具（系统信息 / 计算 / 内网知识查询），供自测接线。

协议：JSON-RPC 2.0 over stdio，逐行一条消息（与官方 MCP stdio 对齐）。
实现仅用标准库 sys/stdin/stdout/json，无第三方依赖。

运行（供 McpRegistry.add_server 拉起）：
    python3 -m aimate.mcp.demo
"""
from __future__ import annotations

import json
import platform
import sys


TOOLS = [
    {
        "name": "sum",
        "description": "计算整数序列之和。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "numbers": {"type": "array", "items": {"type": "number"},
                            "description": "整数列表"}
            },
            "required": ["numbers"],
        },
    },
    {
        "name": "sysinfo",
        "description": "返回本机系统信息（内网信创环境自检）。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "kb_lookup",
        "description": "查询内网知识库条目（演示工具接入 RAG）。",
        "inputSchema": {
            "type": "object",
            "properties": {"key": {"type": "string", "description": "要查询的关键内容"}},
            "required": ["key"],
        },
    },
]


def _handle_tool(name: str, args: dict) -> dict:
    if name == "sum":
        nums = [int(x) for x in args.get("numbers", [])]
        return {"content": [{"type": "text",
                             "text": f"总和 = {sum(nums)}"}]}
    if name == "sysinfo":
        info = {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "machine": platform.machine(),
        }
        return {"content": [{"type": "text", "text": json.dumps(info, ensure_ascii=False)}]}
    if name == "kb_lookup":
        key = args.get("key", "")
        text = ("AIMate 支持私有化内网部署，数据不出域。" if "内网" in key
                else f"[内网知识库] 关于「{key}」的条目。")
        return {"content": [{"type": "text", "text": text}]}
    return {"content": [{"type": "text", "text": f"未知工具: {name}"}]}


def main() -> None:
    initialized = False
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = msg.get("method")
        rid = msg.get("id")
        result = None
        error = None
        if method == "initialize":
            initialized = True
            result = {"protocolVersion": "2024-11-05",
                      "capabilities": {"tools": {}},
                      "serverInfo": {"name": "aimate-demo-mcp", "version": "0.1.0"}}
        elif method == "notifications/initialized":
            # 通知：无需回包
            continue
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            params = msg.get("params", {})
            try:
                result = _handle_tool(params.get("name", ""), params.get("arguments", {}))
            except Exception as e:  # noqa: BLE001
                error = {"code": -32000, "message": str(e)}
        else:
            error = {"code": -32601, "message": f"未知方法: {method}"}
        resp = {"jsonrpc": "2.0", "id": rid}
        if error:
            resp["error"] = error
        else:
            resp["result"] = result
        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
