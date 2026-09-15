"""IM 通道（企微/钉钉/飞书）统一契约。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InboundMessage:
    """跨通道统一入站消息契约。

    channels.* 各通道的 verify/decrypt/parse 应产出一条 InboundMessage，
    交给统一调度器分发给数字员工。
    """
    channel: str          # "wecom" | "dingtalk" | "feishu"
    tenant_id: str
    from_user: str
    text: str
    raw: dict = field(default_factory=dict)
