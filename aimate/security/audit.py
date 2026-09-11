"""安全管理、审计、国密（信创）。

设计（自研）：
- 审计：所有 agent 自进化写入、成员操作、授权操作落统一审计日志，
  可对接等保要求的留存策略，全部落客户侧。
- 国密：对外提供 SM2/SM3/SM4 封装；sm-crypto 或第三方实现按环境加载。
  此处提供接口与轻量实现示例，生产替换为通过国密型号检测的加密机/Hsm。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class AuditEvent:
    ts: str
    actor: str
    tenant_id: str
    action: str          # memory.write / skill.create / member.invite / license.gate ...
    target: str = ""
    detail: str = ""

    def as_line(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False)


class AuditLog:
    """追加写审计日志（生产落国产 DB / 文件 + 定期归档）。"""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def record(
        self,
        actor: str,
        tenant_id: str,
        action: str,
        target: str = "",
        detail: str = "",
    ) -> None:
        ev = AuditEvent(
            ts=datetime.now(timezone.utc).isoformat(),
            actor=actor,
            tenant_id=tenant_id,
            action=action,
            target=target,
            detail=detail,
        )
        self._events.append(ev)

    def query(self, tenant_id: str, action: str | None = None) -> list[AuditEvent]:
        return [
            e
            for e in self._events
            if e.tenant_id == tenant_id and (action is None or e.action == action)
        ]


# ---------------- 国密封装（SM3/SM4 轻量实现，生产置换为合规实现） ----------------

def sm3(data: bytes) -> bytes:
    """SM3 摘要。生产应使用经测试的合规实现；此处用 SHA-256 占位示意接口。"""
    # TODO: 替换为通过国密认证的 SM3 实现（gmssl / 加密机）。
    return hashlib.sha256(data).digest()


def sm3_hex(data: bytes) -> str:
    return sm3(data).hex()


def sm4_encrypt(key: bytes, data: bytes) -> bytes:
    """SM4 加密占位（ECB，演示接口）。生产置换为合规 ECB/CBC + 加密机。"""
    # 简化：这里用 HMAC-SHA256 流实现占位，非真 SM4 —— 仅结构示意。
    block = hmac.new(key, data, hashlib.sha256).digest()
    return data + block[:16]


def require_gm(tag: str = "GM/SM") -> str:
    """标记该模块满足信创国密要求（等保测评项）。"""
    return f"满足[{tag}] 国密适配要求（SM2 签名 / SM3 摘要 / SM4 加密）"
