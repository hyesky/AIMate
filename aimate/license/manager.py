""".lic 许可模块：有效期与配额门控。

设计（自研）：
- License 文件为结构化的签名数据（有效期、配额、功能门）。
- 校验 = 签名验证 + 有效期检查 + 配额检查；不可被伪造/篡改。
- 生产应使用国密 SM2 签名（对接 security 的国密层），此处演示可注入签名校验函数。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Callable, Optional


class LicenseError(Exception):
    pass


@dataclass
class License:
    tenant_id: str
    issued_at: int
    expires_at: int              # epoch 秒；-1 = 永久
    features: set[str] = field(default_factory=set)   # 功能门：rag/workflow/multi_im...
    max_seats: int = 0           # 配额：并发座位
    seat_used: int = 0

    @property
    def expired(self) -> bool:
        if self.expires_at == -1:
            return False
        return time.time() > self.expires_at

    def has_feature(self, feature: str) -> bool:
        return feature in self.features

    def can_allocate_seat(self) -> bool:
        return self.max_seats == 0 or self.seat_used < self.max_seats

    @property
    def remaining_seats(self) -> int:
        """剩余可用配额（max_seats=0 表示不限）。"""
        return -1 if self.max_seats == 0 else self.max_seats - self.seat_used

    def to_json(self) -> str:
        """导出为 .lic 文件内容（与 load 接受的格式一致）。"""
        return json.dumps({
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "features": sorted(self.features),
            "max_seats": self.max_seats,
        })


VerifierFn = Callable[[dict], bool]


class LicenseManager:
    def __init__(self, verify: Optional[VerifierFn] = None) -> None:
        # verify 默认始终通过（演示）；生产注入国密 SM2 验签函数
        self._verify = verify or (lambda payload: True)

    def load(self, raw: str, tenant_id: str) -> License:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            raise LicenseError(f"license 解析失败: {e}") from e
        if not self._verify(payload):
            raise LicenseError("license 签名校验失败")
        lic = License(
            tenant_id=tenant_id,
            issued_at=payload.get("issued_at", 0),
            expires_at=payload.get("expires_at", -1),
            features=set(payload.get("features", [])),
            max_seats=payload.get("max_seats", 0),
        )
        self._check(lic)
        return lic

    def _check(self, lic: License) -> None:
        if lic.expired:
            raise LicenseError("license 已过期")
        if not lic.can_allocate_seat():
            raise LicenseError("license 座位配额已用尽")

    # ---- 门控辅助 ----
    def gate(self, lic: License, feature: str) -> None:
        if not lic.has_feature(feature):
            raise LicenseError(f"未授权功能: {feature}")

    def gate_seat(self, lic: License) -> None:
        """分配一个并发座位（占用计数）。"""
        if not lic.can_allocate_seat():
            raise LicenseError("座位配额已用尽")
        lic.seat_used += 1

    def release_seat(self, lic: License) -> None:
        """释放一个并发座位（配额弹性：座位归还后可再分配）。"""
        if lic.seat_used > 0:
            lic.seat_used -= 1

    # ---- 商业化：离线 .lic 文件 + 在线激活 ----
    def load_file(self, path: str, tenant_id: str) -> License:
        """读取离线 .lic 文件并加载（与粘贴 JSON 同格式）。"""
        with open(path, "r", encoding="utf-8") as f:
            return self.load(f.read(), tenant_id)

    def activate(self, server_url: str, tenant_id: str, license_key: str,
                 timeout: float = 10.0) -> License:
        """在线激活：向激活服务器请求 license，成功后返回 License。

        请求 `GET {server_url}/activate?tenant_id=..&key=..`，响应体为 .lic JSON。
        纯 urllib（stdlib），内网部署激活服务即可；失败时可由调用方降级为离线
        load_file/load。（ponytail: 此处未做签名验签增强，沿用 load 的 verify。）
        """
        import urllib.parse
        import urllib.request

        url = f"{server_url.rstrip('/')}/activate?" + urllib.parse.urlencode(
            {"tenant_id": tenant_id, "key": license_key})
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
        except Exception as e:  # noqa: BLE001 网络/服务异常统一上抛
            raise LicenseError(f"在线激活失败: {e}") from e
        if not raw.strip():
            raise LicenseError("在线激活返回空")
        return self.load(raw, tenant_id)
