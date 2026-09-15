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
    owner: str = ""                   # 'agent' 表示 agent-created，可被 Curator 处理
    pinned: bool = False              # pinned 技能跳过一切自动状态迁移
    review_note: str = ""             # 审核意见（驳回/通过时填写）
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    last_used_at: str = field(default_factory=_now)


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

    # ---- 企业自建审批流：draft → pending_review → published / rejected ----
    @staticmethod
    def _can_transition(current: SkillStatus, target: SkillStatus) -> bool:
        flow = {
            SkillStatus.DRAFT: {SkillStatus.PENDING_REVIEW, SkillStatus.ARCHIVED},
            SkillStatus.PENDING_REVIEW: {SkillStatus.PUBLISHED, SkillStatus.ARCHIVED,
                                         SkillStatus.DRAFT},  # 驳回退回草稿
            SkillStatus.PUBLISHED: {SkillStatus.ARCHIVED},
            SkillStatus.ARCHIVED: {SkillStatus.DRAFT},
        }
        return target in flow.get(current, set())

    def submit(self, tenant_id: str, name: str) -> Skill:
        """草稿提交审核：draft → pending_review。"""
        s = self.get(tenant_id, name)
        if not s:
            raise KeyError(name)
        if not self._can_transition(s.status, SkillStatus.PENDING_REVIEW):
            raise ValueError(f"当前状态 {s.status.value} 不能提交审核")
        s.status = SkillStatus.PENDING_REVIEW
        s.updated_at = _now()
        return s

    def review(self, tenant_id: str, name: str, approve: bool, note: str = "") -> Skill:
        """审核：pending_review → published(通过) 或 退回 draft(驳回)。"""
        s = self.get(tenant_id, name)
        if not s:
            raise KeyError(name)
        if s.status != SkillStatus.PENDING_REVIEW:
            raise ValueError(f"只有待审核状态可审核(当前 {s.status.value})")
        target = SkillStatus.PUBLISHED if approve else SkillStatus.DRAFT
        if not self._can_transition(s.status, target):
            raise ValueError("非法状态迁移")
        s.status = target
        s.review_note = note
        s.updated_at = _now()
        return s

    def list(self, tenant_id: str, status: SkillStatus | None = None) -> list[Skill]:
        return [
            s
            for s in self._skills.values()
            if s.tenant_id == tenant_id and (status is None or s.status == status)
        ]

    # ---- 渐进披露（借鉴思想：技能不全量注入系统提示，索引用到再加载,省 token）----
    def index_of(self, tenant_id: str, status: SkillStatus | None = None) -> list[dict]:
        """返回轻量索引(仅 name+description+trigger)，供系统提示注入。"""
        return [
            {"name": s.name, "description": s.description, "trigger": s.trigger}
            for s in self.list(tenant_id, status)
        ]

    def load(self, tenant_id: str, name: str) -> str | None:
        """按需加载完整 body（索引用到某技能时才读取全文）。"""
        s = self.get(tenant_id, name)
        if not s or s.status == SkillStatus.ARCHIVED:
            return None
        return s.body

    def use(self, tenant_id: str, name: str) -> None:
        """记录一次使用，刷新 last_used_at（供给 Curator 算活动度）。"""
        s = self.get(tenant_id, name)
        if s:
            s.last_used_at = _now()


class Curator:
    """技能策展人（自我进化）：后台维护技能生命周期。

    借鉴开源 agent 的设计思想（AIMate 自研落地）：
    - **惰性触发**：不常驻定时器，由 maybe_run() 按『距上次运行超过 interval_hours
      且 agent 空闲』判定是否该跑一轮。
    - **只归档、永不硬删**：归档可恢复。
    - **分级阈值**：stale_days 后标记闲置、archive_days 后归档，由活动时间推算。
    - **pinned 保护**：pinned 技能跳过一切自动迁移；只处理 agent-created。
    - **consolidate 默认关**：有观点且耗辅助模型成本，默认不开。
    """

    def __init__(self, store: SkillStore, *, interval_hours: int = 24 * 7,
                 stale_days: int = 30, archive_days: int = 90) -> None:
        self.store = store
        self.interval_hours = interval_hours
        self.stale_days = stale_days
        self.archive_days = archive_days
        self.last_run_at: str | None = None

    def maybe_run(self, *, idle: bool = True, now: datetime | None = None) -> bool:
        """惰性判定是否需要跑一轮策展。True 表示执行了。"""
        now = now or datetime.now(timezone.utc)
        if not idle:
            return False  # agent 忙时不打扰
        if self.last_run_at is not None:
            last = datetime.fromisoformat(self.last_run_at)
            if (now - last).total_seconds() < self.interval_hours * 3600:
                return False  # 距上次太近
        self.last_run_at = now.isoformat()
        return True

    def _age_hours(self, skill: Skill) -> float:
        base = skill.last_used_at or skill.updated_at
        return _hours_since(base)

    def archive_unused(self, tenant_id: str, used_names: set[str]) -> list[str]:
        """把 agent 自沉淀且超过 archive_days 未活动的技能归档（不删除，可恢复）。"""
        archived: list[str] = []
        for s in self.store.list(tenant_id, SkillStatus.PUBLISHED):
            if s.pinned or s.owner != "agent":
                continue                       # pinned 或用一口径技能不自动处理
            if s.name in used_names:
                s.last_used_at = _now()        # 被调用了，刷新活动时间
                continue
            if self._age_hours(s) > self.archive_days * 24:
                s.status = SkillStatus.ARCHIVED
                archived.append(s.name)
        return archived

    def mark_stale(self, tenant_id: str, used_names: set[str]) -> list[str]:
        """超过 stale_days 未活动且非 pinned 的 agent-created 技能标记为闲置(提示关注)。"""
        stale: list[str] = []
        for s in self.store.list(tenant_id, SkillStatus.PUBLISHED):
            if s.pinned or s.owner != "agent":
                continue
            if s.name not in used_names and self._age_hours(s) > self.stale_days * 24:
                stale.append(s.name)
        return stale


def _hours_since(iso: str) -> float:
    from datetime import datetime
    dt = datetime.fromisoformat(iso)
    return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
