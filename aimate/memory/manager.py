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


# ---------------------------------------------------------------------------
# Provider 模式 + 后台异步 prefetch / ingest
# 借鉴思想：turn 前预取(recall)、turn 后写回(ingest)，异步不阻塞主循环。
# AIMate 自研：线程池执行；门控由 memory.gate.is_trivial_prompt 决定是否值得。
# ---------------------------------------------------------------------------
from concurrent.futures import ThreadPoolExecutor


class MemoryManagerAsync(MemoryManager):
    """在 MemoryManager 基础上提供后台异步 prefetch/ingest + 记忆提供者钩子。"""

    def __init__(self, workers: int = 2) -> None:
        super().__init__()
        self._pool = ThreadPoolExecutor(max_workers=workers)
        self.providers: list[object] = []      # 可选外部记忆后端(Honcho/自研)

    def add_provider(self, provider: object) -> None:
        """注册一个记忆后端。内部约定：initialize()/prefetch()/ingest()/shutdown()。"""
        if callable(getattr(provider, "initialize", None)):
            provider.initialize()
        self.providers.append(provider)

    def prefetch(self, tenant_id: str, owner: str, text: str) -> None:
        """会话/回合前预取：后台把相关记忆提前召回(不阻塞)。"""
        from aimate.memory.gate import is_trivial_prompt
        if is_trivial_prompt(text):
            return
        for p in self.providers:
            fn = getattr(p, "prefetch", None)
            if callable(fn):
                self._pool.submit(_safe, fn, tenant_id, owner, text)

    def ingest(self, tenant_id: str, owner: str, user_text: str, assistant_text: str) -> None:
        """会话/回合后写回：后台抽取并持久化记忆。"""
        from aimate.memory.gate import is_trivial_prompt
        if not user_text or is_trivial_prompt(user_text):
            return
        for p in self.providers:
            fn = getattr(p, "ingest", None)
            if callable(fn):
                self._pool.submit(_safe, fn, tenant_id, owner, user_text, assistant_text)

    def shutdown(self, wait: bool = False) -> None:
        self._pool.shutdown(wait=wait)


def _safe(fn, *args):
    try:
        fn(*args)
    except Exception:  # noqa: BLE001 后台任务异常不阻塞主流程
        pass
