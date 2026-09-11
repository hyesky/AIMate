"""网关认证与授权（gateway/auth）。

统一接入层入口：校验调用方身份，映射到 Member/Role，执行 RBAC。
支持多种认证方式：OpenAPI 密钥、Anthropic-API key、IM 通道签名。
"""
from __future__ import annotations

import hmac
import hashlib
from dataclasses import dataclass
from typing import Optional

from aimate.org.service import OrgService, Member, Role


@dataclass
class Principal:
    actor: str
    tenant_id: str
    role: Role
    source: str        # openapi / anthropic / feishu / dingtalk / wecom / web


class GatewayAuth:
    def __init__(self, org: OrgService) -> None:
        self.org = org
        self._api_keys: dict[str, tuple[str, Role]] = {}   # key -> (tenant, role)

    def issue_api_key(self, tenant_id: str, role: Role = Role.MEMBER) -> str:
        import secrets
        key = "amk_" + secrets.token_urlsafe(24)
        self._api_keys[key] = (tenant_id, role)
        return key

    def authenticate_api_key(self, key: str) -> Principal | None:
        hit = self._api_keys.get(key)
        if not hit:
            return None
        tenant, role = hit
        return Principal(actor=key, tenant_id=tenant, role=role, source="openapi")

    def authenticate_im_signature(
        self, tenant_id: str, *, secret_key: bytes, body: bytes, req_signature: str
    ) -> bool:
        """IM 回调签名校验（企微/钉钉/飞书通用模式）。"""
        expect = hmac.new(secret_key, body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expect, req_signature)

    def resolve_member(self, principal: Principal, member_id: str) -> Member | None:
        m = self.org._members.get(member_id)
        return m if m and m.tenant_id == principal.tenant_id else None
