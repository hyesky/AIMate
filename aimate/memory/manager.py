"""有界且经筛选的持久记忆：跨会话保持，Agent 自行 add/replace/remove。

设计要点（自研，多租户版）：
- 按 tenant + owner 隔离，记忆落客户侧（私有化内网）。
- 有界预算（budget_chars）：超限时 Agent 自行合并/替换条目腾空间（自我筛选）。
- 提供 add / replace / remove 三操作，replace/remove 用短唯一子串匹配。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


class MemoryBudgetExceeded(Exception):
    pass


@dataclass
class MemoryStore:
    tenant_id: str
    owner: str
    target: str          # 'memory'（Agent 笔记） / 'user'（用户偏好）
    entries: list[str]
    budget_chars: int


class MemoryManager:
    """内存态实现；生产可对接国产数据库/SQLite/向量库持久化。"""

    def __init__(self) -> None:
        self._stores: dict[tuple[str, str, str], MemoryStore] = {}

    def _key(self, tenant_id: str, owner: str, target: str) -> tuple[str, str, str]:
        return (tenant_id, owner, target)

    def ensure(
        self, tenant_id: str, owner: str, target: str, budget_chars: int
    ) -> MemoryStore:
        k = self._key(tenant_id, owner, target)
        if k not in self._stores:
            self._stores[k] = MemoryStore(tenant_id, owner, target, [], budget_chars)
        return self._stores[k]

    def add(self, tenant_id: str, owner: str, target: str, content: str) -> bool:
        store = self.ensure(tenant_id, owner, target, 2200)
        new_len = sum(len(e) for e in store.entries) + len(content)
        if new_len > store.budget_chars:
            raise MemoryBudgetExceeded(
                f"{target} 记忆已满（{store.budget_chars} 字符），需合并/替换旧条目再写入"
            )
        store.entries.append(content)
        return True

    def replace(
        self, tenant_id: str, owner: str, target: str, old_text: str, content: str
    ) -> bool:
        """用子串匹配唯一旧条目，替换为新内容。"""
        store = self.ensure(tenant_id, owner, target, 2200)
        matches = [i for i, e in enumerate(store.entries) if old_text in e]
        if len(matches) != 1:
            raise ValueError(
                f"old_text 需唯一匹配一条（当前匹配 {len(matches)} 条），请更具体"
            )
        store.entries[matches[0]] = content
        return True

    def remove(self, tenant_id: str, owner: str, target: str, old_text: str) -> bool:
        store = self.ensure(tenant_id, owner, target, 2200)
        matches = [i for i, e in enumerate(store.entries) if old_text in e]
        if len(matches) != 1:
            raise ValueError(f"old_text 需唯一匹配一条（当前匹配 {len(matches)} 条）")
        store.entries.pop(matches[0])
        return True

    def snapshot(self, tenant_id: str, owner: str, target: str) -> str:
        """会话开始时取冻结快照，注入系统提示。"""
        store = self.ensure(tenant_id, owner, target, 2200)
        used = sum(len(e) for e in store.entries)
        pct = int(used / max(store.budget_chars, 1) * 100)
        block = f"[{target.upper()} MEMORY — {pct}% ({used}/{store.budget_chars} chars)]\n"
        block += "\n§\n".join(store.entries)
        return block
