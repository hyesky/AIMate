"""企微通道（骨架）。

生产接线：接收企微回调（AES 加解密 + 签名校验），解出统一 InboundMessage，
转交统一调度器。依赖 defusedxml 解析 XML + 企微加解密。
"""
from __future__ import annotations

from dataclasses import dataclass, field


class WecomChannel:
    def __init__(self, corp_id: str, agent_id: str, secret: str, token: str, encoding_aes_key: str) -> None:
        self.corp_id = corp_id
        self.agent_id = agent_id
        self.secret = secret
        self.token = token
        self.encoding_aes_key = encoding_aes_key

    def verify_signature(self, msg_signature: str, timestamp: str, nonce: str, echostr: str) -> bool:
        import hashlib
        parts = sorted([self.token, timestamp, nonce, echostr])
        return hashlib.sha1("".join(parts).encode()).hexdigest() == msg_signature
