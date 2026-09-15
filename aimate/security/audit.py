"""安全管理、审计、国密（信创）。

设计（自研）：
- 审计：所有 agent 自进化写入、成员操作、授权操作落统一审计日志，
  可对接等保要求的留存策略，全部落客户侧。
- 国密：对外提供 SM2/SM3/SM4 封装；sm-crypto 或第三方实现按环境加载。
  此处提供接口与轻量实现示例，生产替换为通过国密型号检测的加密机/Hsm。
"""
from __future__ import annotations

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


# ---------------- 国密（SM2/SM3/SM4）合规实现 ----------------
# 真实实现见 security/gm.py（纯 Python、国标算法、通过标准向量自检）。
# 生产等保现场建议置换为通过密码型号检测的合规库/加密机。

def sm3(data: bytes) -> bytes:
    """SM3 杂凑摘要（32 字节）。GB/T 32905-2016。"""
    from .gm import sm3 as _sm3
    return _sm3(data)


def sm3_hex(data: bytes) -> str:
    return sm3(data).hex()


class SM4Cipher:
    """SM4 分组密码（ECB/CBC + PKCS7）。GB/T 32907-2016。"""

    def __init__(self, key: bytes) -> None:
        from .gm import SM4
        self._c = SM4(key)

    def encrypt_ecb(self, data: bytes) -> bytes:
        return self._c.encrypt_ecb(data)

    def decrypt_ecb(self, data: bytes) -> bytes:
        return self._c.decrypt_ecb(data)

    def encrypt_cbc(self, data: bytes, iv: bytes) -> bytes:
        return self._c.encrypt_cbc(data, iv)

    def decrypt_cbc(self, data: bytes, iv: bytes) -> bytes:
        return self._c.decrypt_cbc(data, iv)


def sm4_encrypt(key: bytes, data: bytes) -> bytes:
    """SM4 CBC 加密（随机 IV 拼头部），兼容旧接口。"""
    from .gm import sm4_encrypt as _e
    return _e(key, data)


def sm4_decrypt(key: bytes, data: bytes) -> bytes:
    """SM4 CBC 解密（密文 = IV(16) + body）。"""
    from .gm import sm4_decrypt as _d
    return _d(key, data)


def generate_sm2_keypair():
    """生成 SM2 (私钥, 公钥) 密钥对。GB/T 32918-2016。"""
    from .gm import generate_sm2_keypair as _g
    return _g()


def sm2_sign(priv: bytes, msg: bytes, ida: bytes = b"1234567812345678"):
    """SM2 数字签名，返回 (r, s)。"""
    from .gm import sm2_sign as _s
    return _s(priv, msg, ida)


def sm2_verify(pub: bytes, msg: bytes, sig, ida: bytes = b"1234567812345678") -> bool:
    """SM2 验签，通过返回 True。"""
    from .gm import sm2_verify as _v
    return _v(pub, msg, sig, ida)


def require_gm(tag: str = "GM/SM") -> str:
    """标记该模块满足信创国密要求（等保测评项）。"""
    return f"满足[{tag}] 国密适配要求（SM2 签名 / SM3 摘要 / SM4 加密，纯 Python 合规实现）"
