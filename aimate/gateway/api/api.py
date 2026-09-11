"""统一接入 API（gateway/api）：OpenAPI / Anthropic-API。

把服务端能力以开放接口暴露：
- /openapi/* ：管理 + 数字员工调度（企业自建客户端接入）。
- /anthropic/* ：兼容 Anthropic Messages API，让 AI 工具链即插即用。
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from aimate.agents.core import Agent, get
from aimate.gateway.auth.auth import GatewayAuth, Principal


@dataclass
class ChatRequest:
    agent_id: str
    messages: list[dict]
    tenant_id: str = ""
    stream: bool = False


class GatewayAPI:
    def __init__(self, auth: GatewayAuth) -> None:
        self.auth = auth
        self._external_tools: list[dict] = []

    # ---- 通用调度 ----
    def dispatch(self, principal: Principal, req: ChatRequest) -> dict:
        agent = get(req.agent_id, req.tenant_id)
        if not agent:
            raise LookupError(f"agent {req.agent_id} 不存在或不在该租户")
        # 此处仅路由骨架；真实推理转发到内网 LLM 网关（rag/agents 装配）。
        session_id = uuid.uuid4().hex[:12]
        return {
            "session_id": session_id,
            "agent": agent.name,
            "model": agent.model,
            "message_count": len(req.messages),
            "echo": req.messages[-1] if req.messages else None,
        }

    # ---- Anthropic-API 兼容 ----
    def anthropic_messages(self, body: dict) -> dict:
        """Anthropic Messages API 兼容入口：返回 SSE 风格文本块（简化非流式）。"""
        model = body.get("model", "claude-3-5-haiku")
        prompt = "".join(
            m.get("content", "") for m in body.get("messages", [])
        )
        return {
            "id": f"msg_{uuid.uuid4().hex[:12]}",
            "type": "message",
            "model": model,
            "content": [{"type": "text", "text": f"[AIMate 已接收指令: {prompt[:64]}]"}],
            "stop_reason": "end_turn",
        }

    # -----------------------------------------------
    # 工具 schema 归一化（借鉴思想：防严格 provider 拒收整个 toolset）
    # 不同 provider 期望不同的工具 schema 形状：裸函数 schema 或已包成
    # OpenAI tool({"type":"function","function":{...}})。再次包装会让严格
    # provider(如 DeepSeek) 报 tools[N].function: missing field name 并拒收
    # 整个请求。这里把两种形状归一到裸函数 schema，无法解析的丢弃并告警，
    # 不影响其余工具。AIMate 自研实现（仅借鉴"该归一化"这一思想）。
    # -----------------------------------------------
    @staticmethod
    def normalize_tool_schema(schema: Any) -> dict | None:
        if not isinstance(schema, dict):
            return None
        # 解开已包成 OpenAI tool 的条目 -> 取内层 function
        if schema.get("type") == "function" and isinstance(schema.get("function"), dict):
            schema = schema["function"]
            if not isinstance(schema, dict):
                return None
        name = schema.get("name", "")
        if not name or not isinstance(name, str):
            return None
        return schema

    # 动态工具集：给数字员工暴露的外部工具（技能、RAG 检索、命令等）。
    def tool_schemas(self) -> list[dict]:
        """返回规整后的工具 schema 列表（openai tool 包裹形式）。"""
        out: list[dict] = []
        for raw in self._external_tools:
            norm = self.normalize_tool_schema(raw)
            if norm is None:
                continue  # 丢弃坏 schema，不拖垮整个 toolset
            out.append({"type": "function", "function": norm})
        return out

    def register_tool(self, schema: dict) -> bool:
        """注册一个外部工具（裸函数 schema 或已包装 tool schema）。"""
        if self.normalize_tool_schema(schema) is None:
            return False
        self._external_tools.append(schema)
        return True
