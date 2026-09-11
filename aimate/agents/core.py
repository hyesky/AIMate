"""数字员工与 Agent 池：负责「能干活」的运行时核心。"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable


class AgentStatus(str, Enum):
    IDLE = "idle"
    BUSY = "busy"
    OFFLINE = "offline"


@dataclass
class Agent:
    """一个数字员工 = 人格(SOUL) + 技能集 + 记忆 + 模型绑定。

    借鉴开源 agent 蓝本的「人格注入 + 技能渐进披露 + 有界记忆」思想，
    但为多租户企业场景自研：每个 Agent 隶属于组织，记忆/技能按租户隔离。
    """

    id: str
    name: str
    tenant_id: str
    role: str = "employee"          # employee / expert / ops ...
    soul_md: str = ""               # 人格与行为边界（企业人设模板下发）
    model: str = "inner-gateway"    # 指向内网推理网关
    skill_names: list[str] = field(default_factory=list)
    memory_budget_chars: int = 2200  # 有界记忆，防膨胀
    status: AgentStatus = AgentStatus.IDLE

    def with_skill(self, name: str) -> "Agent":
        if name not in self.skill_names:
            self.skill_names.append(name)
        return self


# 简单内存 Agent 池（生产可换 Redis/多节点注册）
_AGENT_POOL: dict[str, Agent] = {}


def register(agent: Agent) -> None:
    _AGENT_POOL[agent.id] = agent


def get(agent_id: str, tenant_id: str | None = None) -> Agent | None:
    a = _AGENT_POOL.get(agent_id)
    if tenant_id and a and a.tenant_id != tenant_id:
        return None
    return a


def list_by_tenant(tenant_id: str) -> list[Agent]:
    return [a for a in _AGENT_POOL.values() if a.tenant_id == tenant_id]
