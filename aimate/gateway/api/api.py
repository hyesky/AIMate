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
from aimate.llm.gateway import LLMError


@dataclass
class ChatRequest:
    agent_id: str
    messages: list[dict]
    tenant_id: str = ""
    stream: bool = False


class GatewayAPI:
    def __init__(self, auth: GatewayAuth, system: "object | None" = None) -> None:
        self.auth = auth
        self.system = system  # 装配好的 System（提供 memory/rag/llm/skills）
        self._external_tools: list[dict] = []

    # ---- 通用调度 ----
    def dispatch(self, principal: Principal, req: ChatRequest) -> dict:
        agent = get(req.agent_id, req.tenant_id)
        if not agent:
            raise LookupError(f"agent {req.agent_id} 不存在或不在该租户")
        session_id = uuid.uuid4().hex[:12]

        # 未装配内网 LLM -> 维持原有路由骨架回显（骨架模式）
        if not self.system or not self.system.llm or not self.system.llm._backends:
            return {
                "session_id": session_id,
                "agent": agent.name,
                "model": agent.model,
                "message_count": len(req.messages),
                "echo": req.messages[-1] if req.messages else None,
            }

        # 装配系统提示：SOUL(人格/边界) + 记忆 + RAG 检索上下文
        sys_parts: list[str] = []
        if agent.soul_md:
            sys_parts.append(agent.soul_md)
        try:
            mem = self.system.memory.snapshot(req.tenant_id, agent.id, "memory")
            sys_parts.append(mem)
        except Exception:  # noqa: BLE001 记忆未建不影响推理
            pass
        try:
            last_user = next(
                (m.get("content", "") for m in reversed(req.messages)
                 if m.get("role") == "user"), "")
            if last_user:
                ctx = self.system.search_kb(last_user)
                if ctx:
                    ctx_txt = "\n".join(f"- {h.text}" for h in ctx[:3])
                    sys_parts.append(f"[知识库参考]\n{ctx_txt}")
        except Exception:  # noqa: BLE001 RAG 失败不回退推理
            pass
        system_prompt = "\n\n".join(p for p in sys_parts if p)

        # 组装对话请求
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        messages += req.messages

        try:
            alias = agent.model or self.system.llm_default
            tools = self.tool_schemas() or None
            resp = self.system.llm.chat(alias, messages, tools=tools)
            backend = self.system.llm.resolve(alias)
            text = backend.reply_text(resp)
            self.system.audit.record(
                principal.actor, req.tenant_id, "llm.dispatch",
                target=agent.id,
                detail=f"model={backend.config.model} msgs={len(messages)}",
            )
            return {
                "session_id": session_id,
                "agent": agent.name,
                "model": backend.config.model,
                "reply": text,
                "finish_reason": backend.finish_reason(resp),
                "tool_calls": backend.tool_calls(resp),
            }
        except LLMError as e:
            self.system.audit.record(
                principal.actor, req.tenant_id, "llm.error",
                target=agent.id, detail=str(e))
            return {
                "session_id": session_id,
                "agent": agent.name,
                "model": agent.model,
                "error": str(e),
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
