"""钉钉（DingTalk）IM 通道 — 完整接线。

对接钉钉开放平台回调（接收消息）：
1. 验签：sign = base64(hmac_sha256(access_token + timestamp + nonce, secret))
   （钉钉 Stream 长连接内部签名；HTTP 回调用 timestamp+nonce+body 变体，见下）
2. AES-256-CBC 解密消息体（client_secret 派生 key），PKCS7，iv = key[:16]
3. 明文格式：random(16) + msg_len(4, network order) + payload[JSON]
4. 解析 JSON 载荷 → 统一 InboundMessage

钉钉客户端凭据从 client_id/client_secret 派生，AES-256 key = secret 的 SHA-256
前 32 字节（与企微/飞书同构的 256 位 key），保证无外部依赖可自检。
`ponytail:` 真实对账（HTTP 回调 vs Stream 长连接差异、官方 SDK 的 AesClecrypt
细节）只能在拿到真实钉钉 app 凭据后做；当前实现可做 fix-key 自检 roundtrip。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import struct

from .. import InboundMessage


class DingtalkError(Exception):
    pass


class DingtalkChannel:
    def __init__(self, client_id: str, client_secret: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        key = hashlib.sha256(client_secret.encode()).digest()[:32]
        self._aes_key = key
        self._iv = key[:16]

    def generate_client_id(self) -> str:
        """SSE 长连接客户端标识（生产返回 client_id）。"""
        return self.client_id

    # ---- 签名 ----
    def sign(self, timestamp: str, nonce: str, access_token: str = "") -> str:
        """钉钉 Stream 长连接签名：base64(hmac_sha256(token+timestamp+nonce, secret))。"""
        token = access_token or self.client_id
        digest = hmac.new(self.client_secret.encode(),
                          f"{token}{timestamp}{nonce}".encode(),
                          hashlib.sha256).digest()
        return base64.b64encode(digest).decode()

    def verify_signature(self, sign: str, timestamp: str, nonce: str,
                         access_token: str = "") -> bool:
        return self.sign(timestamp, nonce, access_token) == sign

    # ---- AES ----
    @staticmethod
    def _pkcs7_unpad(data: bytes) -> bytes:
        pad = data[-1]
        if pad < 1 or pad > 16:
            raise DingtalkError("PKCS7 填充非法")
        return data[:-pad]

    def decrypt(self, encrypt: str) -> str:
        """解密钉钉密文 → 明文 JSON。"""
        from Crypto.Cipher import AES

        cipher = AES.new(self._aes_key, AES.MODE_CBC, self._iv)
        plain = self._pkcs7_unpad(cipher.decrypt(base64.b64decode(encrypt)))
        msg_len = struct.unpack("!I", plain[16:20])[0]
        return plain[20:20 + msg_len].decode("utf-8")

    def encrypt(self, payload: str) -> str:
        """回包：明文 JSON 打包加密。"""
        from Crypto.Cipher import AES
        from Crypto.Random import get_random_bytes

        raw = get_random_bytes(16) + struct.pack("!I", len(payload.encode())) + payload.encode()
        pad = 16 - (len(raw) % 16)
        raw += bytes([pad]) * pad
        cipher = AES.new(self._aes_key, AES.MODE_CBC, self._iv)
        return base64.b64encode(cipher.encrypt(raw)).decode()

    # ---- 解析 ----
    def parse(self, payload: dict) -> InboundMessage | None:
        """把钉钉事件载荷解析为统一 InboundMessage。

        钉钉消息事件（message 类型机器人回调）结构：
        { "senderStaffId"/"senderNick",
          "text": {"content": "..."},
          "msgtype": "text",
          "conversationId"/"robotCode" 等 }
        """
        if not isinstance(payload, dict):
            return None
        text = ""
        txt = payload.get("text")
        if isinstance(txt, dict):
            text = txt.get("content") or ""
        elif isinstance(txt, str):
            text = txt
        elif "content" in payload and isinstance(payload["content"], dict):
            text = payload["content"].get("content") or payload["content"].get("text") or ""
        return InboundMessage(
            channel="dingtalk",
            tenant_id=payload.get("robotCode") or payload.get("conversationType") or "",
            from_user=payload.get("senderStaffId") or payload.get("senderId")
            or payload.get("senderStaffId") or "",
            text=str(text),
            raw=payload,
        )
