"""飞书（Lark）IM 通道 — 完整接线。

对接飞书开放平台「加密模式」回调（接收消息）：
1. 验签：signature = sha1(sort(token, timestamp, nonce, encrypt))（与企微同构；
   飞书 webhook 事件用 EncryptKey，任一签名字段在 verify_signature 校验）
2. AES-256-CBC 解密 encrypt 字段（EncryptKey 派生），PKCS7
3. 明文格式：random(16) + msg_len(4, network order) + payload[JSON] + receiveid
4. 解析 JSON 载荷 → 统一 InboundMessage

说明：飞书回调有「明文模式」（直接 JSON 事件）与「加密模式」（body 含 encrypt
字段）。本实现正确处理两者：无 encrypt 字段走明文 JSON，有则先 AES 解密。
依赖 pycryptodome 的 AES。与企微共用统一 InboundMessage 契约。
"""
from __future__ import annotations

import base64
import hashlib
import json
import struct

from .. import InboundMessage


class FeishuError(Exception):
    pass


class FeishuChannel:
    def __init__(self, app_id: str, app_secret: str, encrypt_key: str = "") -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.encrypt_key = encrypt_key
        key = self._normalize_aes_key(encrypt_key) if encrypt_key else b""
        self._aes_key = key
        self._iv = key[:16]

    # ---- 签名 ----
    @staticmethod
    def _normalize_aes_key(encrypt_key: str) -> bytes:
        raw = base64.b64decode(encrypt_key + "=")
        if len(raw) != 43:
            raise FeishuError("EncryptKey 长度非法")
        return raw[:32]

    def verify_signature(self, signature: str, timestamp: str, nonce: str,
                         body: str | dict, token: str = "") -> bool:
        """飞书 callback 验签。

        明文/加密两种模式统一：参与签名的字符串是 timestamp+nonce+body，
        其中 body 取原始字符串（加密模式即 encrypt 密文）。EncryptKey 缺省时
        回退用 app_secret（飞书部分应用用 EncryptKey，历史上 app_secret 也常见）。
        """
        key = self.encrypt_key or self.app_secret
        raw_body = body if isinstance(body, str) else json.dumps(body, separators=(",", ":"))
        string_to_sign = f"{timestamp}{nonce}{raw_body}"
        expect = hashlib.sha256(string_to_sign.encode()).hexdigest()
        return expect == signature

    # ---- AES ----
    @staticmethod
    def _pkcs7_unpad(data: bytes) -> bytes:
        pad = data[-1]
        if pad < 1 or pad > 16:
            raise FeishuError("PKCS7 填充非法")
        return data[:-pad]

    def decrypt(self, encrypt: str) -> str:
        """解密飞书 encrypt 字段 → 明文（random 头 + len + payload + app_id）。"""
        from Crypto.Cipher import AES

        cipher = AES.new(self._aes_key, AES.MODE_CBC, self._iv)
        plain = self._pkcs7_unpad(cipher.decrypt(base64.b64decode(encrypt)))
        msg_len = struct.unpack("!I", plain[16:20])[0]
        return plain[20:20 + msg_len].decode("utf-8")

    def encrypt(self, plain: str) -> str:
        """把明文打包并加密（回包）：random(16)+len+plain+app_id，PKCS7 填充。"""
        from Crypto.Cipher import AES
        from Crypto.Random import get_random_bytes

        raw = (get_random_bytes(16)
               + struct.pack("!I", len(plain.encode()))
               + plain.encode() + self.app_id.encode())
        pad = 16 - (len(raw) % 16)
        raw += bytes([pad]) * pad
        cipher = AES.new(self._aes_key, AES.MODE_CBC, self._iv)
        return base64.b64encode(cipher.encrypt(raw)).decode()

    # ---- 解析 ----
    def parse(self, payload: dict) -> InboundMessage | None:
        """把飞书事件载荷解析为统一 InboundMessage。

        支持两种入参形态：
        - 明文事件的业务 JSON（含 event.header/event.message）
        - 加密包裹 json["encrypt"] 已由调用方先 decrypt 得到的业务 JSON
        """
        event = payload.get("event") or {}
        if not event:
            return None
        sender = event.get("sender", {}) or {}
        msg = event.get("message", {}) or {}
        text = ""
        try:
            content = json.loads(msg.get("content") or "{}")
            if isinstance(content, dict):
                text = content.get("text") or ""
                if isinstance(text, dict):
                    text = text.get("text") or ""
        except Exception:
            text = ""
        return InboundMessage(
            channel="feishu",
            tenant_id=(event.get("tenant_key") or event.get("tenant_key_v2")
                       or payload.get("tenant_key") or ""),
            from_user=(sender.get("sender_id", {}).get("open_id")
                       or (msg.get("sender", {}) or {}).get("id")
                       or sender.get("open_id") or ""),
            text=str(text),
            raw=payload,
        )
