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
