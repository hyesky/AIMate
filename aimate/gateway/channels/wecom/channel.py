"""企微（WeCom）IM 通道 — 完整接线。

对接企微回调协议（微信企业微信开放平台「接收消息」）：
1. 验签：msg_signature = sha1(sort(token, timestamp, nonce, msg_encrypt))
2. AES-256-CBC 解密回调密文（EncodingAESKey），PKCS7 填充
3. 明文格式：random(16) + msg_len(4, network order) + msg[XML] + receiveid
4. 解析明文 XML → 统一 InboundMessage

加密仅用于回包时对明文重新打包（encrypt），供 send 复用。
依赖 pycryptodome 的 AES（Crypto.Cipher.AES）。
"""
from __future__ import annotations

import base64
import hashlib
import struct
import xml.etree.ElementTree as ET

from .. import InboundMessage


class WeComError(Exception):
    pass


class WecomChannel:
    def __init__(self, corp_id: str, agent_id: str, secret: str,
                 token: str, encoding_aes_key: str) -> None:
        self.corp_id = corp_id
        self.agent_id = agent_id
        self.secret = secret
        self.token = token
        key = self._normalize_aes_key(encoding_aes_key)
        self._aes_key = key
        self._iv = key[:16]

    # ---- 签名 ----
    @staticmethod
    def _normalize_aes_key(encoding_aes_key: str) -> bytes:
        """EncodingAESKey 是 base64 编码的 43 字节，需补位解码取前 32 字节作 AES-256 key。"""
        raw = base64.b64decode(encoding_aes_key + "=")
        if len(raw) != 43:
            raise WeComError("EncodingAESKey 长度非法")
        return raw[:32]

    def verify_signature(self, msg_signature: str, timestamp: str, nonce: str,
                         msg_encrypt: str) -> bool:
        """企微签名校验：token/timestamp/nonce/密文 字典序 sha1。"""
        parts = sorted([self.token, timestamp, nonce, msg_encrypt])
        expect = hashlib.sha1("".join(parts).encode()).hexdigest()
        return expect == msg_signature

    # ---- AES ----
    @staticmethod
    def _pkcs7_unpad(data: bytes) -> bytes:
        pad = data[-1]
        if pad < 1 or pad > 16:
            raise WeComError("PKCS7 填充非法")
        return data[:-pad]

    def decrypt(self, msg_encrypt: str) -> str:
        """解密企微回调密文 → 明文（含 random 头、msg_len、XML、receiveid 的原始串）。"""
        from Crypto.Cipher import AES

        cipher = AES.new(self._aes_key, AES.MODE_CBC, self._iv)
        plain = self._pkcs7_unpad(cipher.decrypt(base64.b64decode(msg_encrypt)))
        # 前 16 字节是 random；随后 4 字节 network-order 长度
        msg_len = struct.unpack("!I", plain[16:20])[0]
        return plain[20:20 + msg_len].decode("utf-8")

    def encrypt(self, plain: str) -> str:
        """把明文打包并加密（回包）：random(16)+len+plain+corp_id，PKCS7 填充。"""
        from Crypto.Cipher import AES
        from Crypto.Random import get_random_bytes

        raw = (get_random_bytes(16)
               + struct.pack("!I", len(plain.encode()))
               + plain.encode() + self.corp_id.encode())
        pad = 16 - (len(raw) % 16)
        raw += bytes([pad]) * pad
        cipher = AES.new(self._aes_key, AES.MODE_CBC, self._iv)
        return base64.b64encode(cipher.encrypt(raw)).decode()

    # ---- 解析 ----
    def parse(self, xml: str) -> InboundMessage | None:
        """把企微消息正文(明文 XML)<xml> 解析为统一 InboundMessage。"""
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            return None
        el = lambda tag: (root.findtext(tag) or "").strip()  # noqa: E731
        msg_type = el("MsgType")
        text = el("Content")
        if msg_type == "text" and not text:
            text = el("Content")
        return InboundMessage(
            channel="wecom",
            tenant_id=el("ToUserName"),
            from_user=el("FromUserName"),
            text=text,
            raw={"msg_id": el("MsgId"), "create_time": el("CreateTime"),
                 "msg_type": msg_type},
        )
