"""内网 MCP 工具库：把数字员工接到标准 Model Context Protocol 工具服务。

信创/私有化要点：MCP 走 **stdio（本地子进程）**，工具代码与数据全程不出域，
可对接任意实现了 JSON-RPC 2.0 over stdio 的 MCP server（Node/Python/Go 写的
可信工具容器、国产工具服务等）。不引入任何 SDK——只用标准库 subprocess + json。

设计（自研，借鉴官方规范思想，不复制源码）：
- **严格 JSON-RPC 2.0**：initialize → tools/list → tools/call，带 id 匹配超时。
- **逐行协议**：stdio 上每行一条 JSON-RPC 消息，与规范对齐。
- **渐进披露**：tools/list 只取 name/description/inputSchema，省 token；
  实际要调用某工具时才走 tools/call。
- **安全护栏**：单次调用硬超时 + select 轮询；工具结果视为不可信数据回填。
"""
from __future__ import annotations

import json
import select
import subprocess
import threading
from typing import Any


class McpError(Exception):
    """MCP 层错误（协议/连接/超时/工具不存在）。"""


def _openai_schema(tool: dict) -> dict | None:
    """把 MCP tools/list 项规整成 OpenAI function schema。"""
    name = tool.get("name", "")
    if not name or not isinstance(name, str):
        return None
    return {
        "name": name,
        "description": tool.get("description", "") or "",
        "parameters": tool.get("inputSchema") or {"type": "object", "properties": {}},
    }


class StdioMcpClient:
    """MCP server 的 stdio 客户端（纯 stdlib，JSON-RPC 2.0 over stdio）。

    用法：
        c = StdioMcpClient(["python", "-m", "my_mcp_server"], timeout=5.0)
        c.start()
        tools = c.list_tools()          # -> [{"name","description","inputSchema"}]
        out = c.call_tool("weather", {"city": "北京"})
        c.close()
    """

    def __init__(self, cmd: list[str], env: dict[str, str] | None = None,
                 timeout: float = 5.0, name: str = "mcp") -> None:
        self.cmd = cmd
        self.env = env or {}
        self.timeout = timeout
        self.name = name
        self._proc: subprocess.Popen | None = None
        self._id = 0
        self._ready = False
        self.server_info: dict = {}
        self._write_lock = threading.Lock()

    # ---- 生命周期 ----
    def start(self) -> None:
        if self._proc is not None:
            return
        self._proc = subprocess.Popen(  # noqa: S603 内网可信 MCP server
            self.cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=(dict(self.env) if self.env else None),
        )
        try:
            rid = self._request({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                 "params": {"protocolVersion": "2024-11-05",
                                            "capabilities": {},
                                            "clientInfo": {"name": "aimate",
                                                           "version": "1.0"}}})
            self.server_info = rid if isinstance(rid, dict) else {}
            self._id = 1
            self._ready = True
            self._write({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except Exception:
            self.close()
            raise

    # ---- 低层 I/O ----
    def _write(self, msg: dict) -> None:
        assert self._proc and self._proc.stdin
        with self._write_lock:
            self._proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()

    def _request(self, msg: dict) -> Any:
        """发送 JSON-RPC 请求，等待并返回同 id 的 result（带 select 超时）。

        通知类消息（无 id）只写不读。
        """
        self._write(msg)
        req_id = msg.get("id")
        if req_id is None:
            return None
        assert self._proc and self._proc.stdout
        fd = self._proc.stdout
        deadline = self.timeout
        while True:
            r, _, _ = select.select([fd], [], [], deadline)
            if not r:
                raise McpError(f"MCP {self.name} 请求超时")
            line = fd.readline()
            if line == "":
                raise McpError(f"MCP {self.name} 进程已退出")
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue  # 忽略非 JSON 输出行（如 server 端 stderr 混入）
            if parsed.get("id") != req_id:
                continue  # 跳过不匹配的响应
            if "error" in parsed:
                raise McpError(f"MCP {self.name} error: {parsed['error']}")
            return parsed.get("result")

    # ---- 工具 API ----
    def list_tools(self) -> list[dict]:
        self._id += 1
        result = self._request({"jsonrpc": "2.0", "id": self._id,
                                "method": "tools/list", "params": {}})
        if isinstance(result, dict):
            return result.get("tools", []) or []
        return []

    def call_tool(self, name: str, arguments: dict) -> Any:
        self._id += 1
        result = self._request({"jsonrpc": "2.0", "id": self._id,
                                "method": "tools/call",
                                "params": {"name": name, "arguments": arguments}})
        if isinstance(result, dict) and result.get("content"):
            parts = []
            for c in result.get("content", []):
                t = c.get("type", "text")
                if t == "text":
                    parts.append(c.get("text", ""))
                elif t == "image":
                    parts.append(f"[image: {c.get('mimeType','')}]")
            return "\n".join(parts) if parts else result
        return result.get("content") if isinstance(result, dict) else result

    def close(self) -> None:
        if self._proc is None:
            return
        try:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        finally:
            self._proc = None
            self._ready = False


class McpRegistry:
    """MCP 工具注册表：管理多个 server，向数字员工暴露统一工具 schema。

    连接时拉取并缓存轻量 schema；调用时才真正下发到对应 server。
    通过 to_openai_tools() 接入 dispatch 的 toolset。
    """

    def __init__(self) -> None:
        self._servers: dict[str, StdioMcpClient] = {}
        self._schemas: dict[str, dict] = {}

    def add_server(self, name: str, cmd: list[str], env: dict[str, str] | None = None,
                   timeout: float = 5.0) -> StdioMcpClient:
        client = StdioMcpClient(cmd, env=env, timeout=timeout, name=name)
        client.start()
        self._servers[name] = client
        self._refresh_schemas()
        return client

    def remove_server(self, name: str) -> None:
        c = self._servers.pop(name, None)
        if c:
            c.close()
        self._schemas = {n: s for n, s in self._schemas.items()
                         if not n.endswith(f"__{name}__")}
        # 重新构建（按 server 前缀归名）
        rebuilt: dict[str, dict] = {}
        for srv, cli in self._servers.items():
            for t in cli.list_tools():
                sch = _openai_schema(t)
                if sch:
                    rebuilt[f"{srv}__{t['name']}"] = sch
        self._schemas = rebuilt

    def _refresh_schemas(self) -> None:
        rebuilt: dict[str, dict] = {}
        for srv, cli in self._servers.items():
            for t in cli.list_tools():
                sch = _openai_schema(t)
                if sch:
                    rebuilt[f"{srv}__{t['name']}"] = sch
        self._schemas = rebuilt

    def list_servers(self) -> list[dict]:
        out = []
        for name, c in self._servers.items():
            out.append({"name": name, "cmd": list(c.cmd),
                        "ready": c._ready, "server_info": c.server_info,
                        "tools": [f"{name}__{t['name']}" for t in c.list_tools()]})
        return out

    def tool_schemas(self) -> list[dict]:
        """返回 openai tool 包裹形式，供 dispatch 传入上游模型。"""
        return [{"type": "function", "function": s} for s in self._schemas.values()]

    def call_tool(self, name: str, arguments: dict) -> Any:
        if "__" in name:
            srv, tool = name.split("__", 1)
            cli = self._servers.get(srv)
            if cli is None:
                raise McpError(f"MCP server 不存在: {srv}")
            return cli.call_tool(tool, arguments)
        raise McpError(f"工具不存在: {name}（应为 <server>__<tool>）")

    def close_all(self) -> None:
        for c in self._servers.values():
            c.close()
        self._servers.clear()
        self._schemas.clear()
