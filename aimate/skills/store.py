"""技能体系：Skill 市场 + 企业自建 + Agent 自沉淀与策展（自我进化）。

设计（自研）：
- Skill = SKILL.md（含 frontmatter：name/description/trigger）+ 可选脚本/模板。
- 生命周期：草稿 → 审核 → 发布 → 版本/回滚（对接管理后端工作流与 RBAC）。
- 自我进化：Agent 可把对话/工作流沉淀为技能（learn），Curator 后台策展
  （pin/归档/合并/修补，永不自动硬删——可恢复）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SkillStatus(str, Enum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    PUBLISHED = "published"
    ARCHIVED = "archived"


@dataclass
class Skill:
    name: str
    tenant_id: str
    description: str = ""
    trigger: str = ""                 # 什么时候该用这个技能
    body: str = ""                    # SKILL.md body
    version: int = 1
    status: SkillStatus = SkillStatus.DRAFT
    owner: str = ""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)


class SkillStore:
    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def create(self, skill: Skill) -> Skill:
        self._skills[f"{skill.tenant_id}:{skill.name}"] = skill
        return skill

    def get(self, tenant_id: str, name: str) -> Skill | None:
        return self._skills.get(f"{tenant_id}:{name}")

    def set_status(self, tenant_id: str, name: str, status: SkillStatus) -> Skill:
        s = self.get(tenant_id, name)
        if not s:
            raise KeyError(name)
        s.status = status
        s.updated_at = _now()
        return s

    def list(self, tenant_id: str, status: SkillStatus | None = None) -> list[Skill]:
        return [
            s
            for s in self._skills.values()
            if s.tenant_id == tenant_id and (status is None or s.status == status)
        ]


class Curator:
    """技能策展人（自我进化）：后台维护技能生命周期。"""

    def __init__(self, store: SkillStore) -> None:
        self.store = store

    def archive_unused(self, tenant_id: str, used_names: set[str]) -> list[str]:
        """把长时间未被调用的 agent-created 技能归档（不删除，可恢复）。"""
        archived: list[str] = []
        for s in self.store.list(tenant_id, SkillStatus.PUBLISHED):
            if s.name not in used_names and _hours_since(s.updated_at) > 24 * 30:
                s.status = SkillStatus.ARCHIVED
                archived.append(s.name)
        return archived


def _hours_since(iso: str) -> float:
    from datetime import datetime
    dt = datetime.fromisoformat(iso)
    return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
