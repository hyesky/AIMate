"""成员与组织：部门树、角色、邀请/导入、RBAC。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Role(str, Enum):
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"
    AUDITOR = "auditor"


@dataclass
class Member:
    id: str
    tenant_id: str
    name: str
    role: Role = Role.MEMBER
    department_id: str | None = None
    disabled: bool = False


@dataclass
class Department:
    id: str
    tenant_id: str
    name: str
    parent_id: str | None = None


class OrgService:
    def __init__(self) -> None:
        self._members: dict[str, Member] = {}
        self._depts: dict[str, Department] = {}

    # ---- 部门树 ----
    def add_dept(self, dept: Department) -> None:
        self._depts[dept.id] = dept

    def dept_tree(self, tenant_id: str) -> list[Department]:
        return [d for d in self._depts.values() if d.tenant_id == tenant_id]

    # ---- 成员 ----
    def add_member(self, m: Member) -> None:
        self._members[m.id] = m

    def import_members(self, rows: list[dict], tenant_id: str) -> int:
        """批量导入（CSV/Excel）：name + role + dept。"""
        n = 0
        for i, r in enumerate(rows):
            m = Member(
                id=r.get("id") or f"u-{tenant_id}-{i}",
                tenant_id=tenant_id,
                name=r.get("name", ""),
                role=Role(r.get("role", "member")),
                department_id=r.get("dept_id"),
            )
            self.add_member(m)
            n += 1
        return n

    # ---- 邀请 ----
    def create_invite(self, tenant_id: str, email: str, role: Role) -> str:
        """生成邀请链接 token（生产应加密签名单次使用）。"""
        return f"inv:{(tenant_id)}_{email}_{role.value}"

    # ---- RBAC ----
    def can(self, member: Member, permission: str) -> bool:
        if member.disabled:
            return False
        if member.role == Role.ADMIN:
            return True
        perms = {
            Role.MEMBER: {"chat", "use_tools", "create_skill"},
            Role.VIEWER: {"chat"},
            Role.AUDITOR: {"audit.read"},
        }
        return permission in perms.get(member.role, set())
